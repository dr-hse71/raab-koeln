import imaplib
import json
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
import anthropic
import os
import datetime
import html
import re
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_secrets():
    """Lädt scripts/secrets.env (falls vorhanden) in os.environ, ohne bereits
    in der Shell gesetzte Variablen zu überschreiben. So funktionieren manueller
    Aufruf und der GitHub-Actions-Lauf (Secrets als Env-Variablen) gleichermaßen."""
    path = os.path.join(SCRIPT_DIR, "secrets.env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def require_env(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit(
            f"Fehler: Umgebungsvariable {name} ist nicht gesetzt. "
            f"Trage sie in {os.path.join(SCRIPT_DIR, 'secrets.env')} ein "
            f"oder exportiere sie in der Shell."
        )
    return value


load_secrets()

# ── Konfiguration ──────────────────────────────────────────────
IMAP_HOST = "mail.netcologne-hosting.de"
IMAP_PORT = 143
IMAP_USER = "newsletter@raab.koeln"
IMAP_PASS = require_env("NETCOLOGNE_PASSWORD")
ANTHROPIC_KEY = require_env("ANTHROPIC_API_KEY")
TZ = ZoneInfo("Europe/Berlin")
OUTPUT_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "output"))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "daily_brief.html")
REPORT_FILE = os.path.join(OUTPUT_DIR, "market_report.html")
HOURS_BACK = 24
MODEL = "claude-sonnet-5-5"
# Hauptquellen für den Marktbericht: Teilstring der Absenderadresse → Anzeigename.
# Diese Mails gehen im Volltext in den Bericht, alle anderen nur als Kurzfassung.
PRIORITY_SENDERS = {
    "@substack.com": "Substack",
    "frankfurt.newsroom@newsletters.lseg.com": "Reuters",
    "realinvestmentadvice.com": "Lance Roberts",
}
SUMMARY_INPUT_CHARS = 4000
REPORT_INPUT_CHARS = 60000
# ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Du bist ein effizienter E-Mail-Assistent. Fasse die folgende E-Mail prägnant zusammen.

Erstelle eine Zusammenfassung mit:
- 3-6 Bullet Points (die wichtigsten Informationen, Kerninhalte, Handlungsaufforderungen)
- Falls es ein Newsletter mit mehreren Artikeln ist: ein Bullet Point pro Artikel
- Maximal 1-2 Sätze pro Bullet Point
- Auf Deutsch, auch wenn die Mail auf Englisch ist

Antworte NUR mit den Bullet Points, keine Einleitung, kein Fazit."""

REPORT_PROMPT = """Du bist Finanzredakteur und schreibst für einen privaten Anleger einen täglichen Marktbericht auf Deutsch. Grundlage sind ausschließlich die Newsletter der letzten 24 Stunden, die du unten bekommst.

Die Hauptquellen (im Volltext) bilden das Rückgrat des Berichts. Führe ihre Aussagen zu einem Gesamtbild zusammen, statt sie Newsletter für Newsletter nacheinander abzuarbeiten: Wo sind sich die Autoren einig, wo widersprechen sie sich? Konkrete Zahlen (Indexstände, Renditen, Kursbewegungen, Termine) sind wertvoll, übernimm sie genau so, wie sie in den Quellen stehen, und erfinde keine.

Die übrigen Mails bekommst du nur als Kurzfassung. Nimm daraus nur auf, was inhaltlich interessant ist (z. B. KI, Wirtschaftspolitik, Analysen), und zwar unter „weitere_themen“. Werbung, Rabattaktionen und Verwaltungsmails lässt du weg.

Gliedere die Abschnitte so, wobei du Abschnitte ohne Inhalt weglässt:
1. Märkte USA
2. Märkte Europa/Deutschland
3. Makro, Zentralbanken & anstehende Termine
4. Einschätzungen der Autoren (wer sieht was, z. B. „Adami/Nathan sehen …“)

„kurzfassung“ enthält die 3–5 wichtigsten Erkenntnisse des Tages. Gib bei jedem Punkt in „quelle“ den Newsletter bzw. Autor an, aus dem er stammt (bei mehreren mit Komma getrennt)."""

_POINT_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "quelle": {"type": "string"}},
    "required": ["text", "quelle"],
    "additionalProperties": False,
}

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "kurzfassung": {"type": "array", "items": _POINT_SCHEMA},
        "abschnitte": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "titel": {"type": "string"},
                    "punkte": {"type": "array", "items": _POINT_SCHEMA},
                },
                "required": ["titel", "punkte"],
                "additionalProperties": False,
            },
        },
        "weitere_themen": {"type": "array", "items": _POINT_SCHEMA},
    },
    "required": ["kurzfassung", "abschnitte", "weitere_themen"],
    "additionalProperties": False,
}


def decode_str(s):
    if s is None:
        return ""
    parts = decode_header(s)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return " ".join(result)


def extract_body(msg):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                charset = part.get_content_charset() or "utf-8"
                body = part.get_payload(decode=True).decode(charset, errors="replace")
                break
            elif ct == "text/html" and "attachment" not in cd and not body:
                charset = part.get_content_charset() or "utf-8"
                raw_html = part.get_payload(decode=True).decode(charset, errors="replace")
                soup = BeautifulSoup(raw_html, "html.parser")
                body = soup.get_text(separator="\n")
    else:
        charset = msg.get_content_charset() or "utf-8"
        body = msg.get_payload(decode=True).decode(charset, errors="replace")

    # HTML-Newsletter liefern viele Leerzeilen; die kosten nur Tokens.
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def priority_source(sender):
    """Anzeigename der Hauptquelle oder None, wenn der Absender keine ist."""
    s = sender.lower()
    for pattern, name in PRIORITY_SENDERS.items():
        if pattern in s:
            return name
    return None


_JUNK_LINK = re.compile(
    r"unsubscribe|abmelden|abbestellen|opt-?out|"
    r"im browser|view (this )?(email )?in.*browser|browser ansehen|webversion|"
    r"datenschutz|privacy|impressum",
    re.IGNORECASE,
)


def _is_junk_link(text, href):
    if _JUNK_LINK.search(text):
        return True
    if href.lower().rsplit("?", 1)[0].endswith((".gif", ".png", ".jpg", ".jpeg")):
        return True
    return False


def extract_links(msg):
    links = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                charset = part.get_content_charset() or "utf-8"
                raw_html = part.get_payload(decode=True).decode(charset, errors="replace")
                soup = BeautifulSoup(raw_html, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    text = a.get_text(strip=True)
                    if (
                        href.startswith("http")
                        and text
                        and len(text) > 3
                        and not _is_junk_link(text, href)
                    ):
                        links.append((text, href))
    seen = set()
    unique = []
    for text, href in links:
        if href not in seen:
            seen.add(href)
            unique.append((text, href))
    return unique[:10]


def fetch_recent_emails():
    now = datetime.datetime.now(TZ)
    cutoff = now - datetime.timedelta(hours=HOURS_BACK)

    print(f"Verbinde mit {IMAP_HOST} als {IMAP_USER}...")
    mail = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
    mail.starttls()
    mail.login(IMAP_USER, IMAP_PASS)
    mail.select("INBOX")

    # IMAP SINCE filtert nur datumsgenau. Wir setzen einen Tag früher an und
    # filtern unten stundengenau gegen cutoff nach.
    since = (cutoff - datetime.timedelta(days=1)).strftime("%d-%b-%Y")
    _, data = mail.search(None, f'(SINCE "{since}")')
    mail_ids = data[0].split()

    emails = []
    for mid in mail_ids:
        _, msg_data = mail.fetch(mid, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        date_str = msg.get("Date", "")
        try:
            msg_dt = parsedate_to_datetime(date_str)
            if msg_dt.tzinfo is None:
                msg_dt = msg_dt.replace(tzinfo=TZ)
        except Exception:
            msg_dt = None

        # Stundengenaue 24h-Grenze (Mails ohne lesbares Datum behalten wir).
        if msg_dt is not None and msg_dt < cutoff:
            continue

        subject = decode_str(msg.get("Subject", "(kein Betreff)"))
        sender = decode_str(msg.get("From", ""))
        date = msg_dt.astimezone(TZ).strftime("%d.%m.%Y %H:%M") if msg_dt else date_str

        body = extract_body(msg)
        links = extract_links(msg)

        emails.append({
            "subject": subject,
            "sender": sender,
            "source": priority_source(sender),
            "date": date,
            "body": body,
            "links": links,
            "sort_dt": msg_dt,
        })

    mail.logout()

    # Chronologisch (älteste zuerst), robust gegen fehlende Datumsangaben.
    emails.sort(key=lambda e: e["sort_dt"] or cutoff)
    print(f"{len(emails)} Mails der letzten {HOURS_BACK}h gefunden.")
    return emails


def create_message(client, **kwargs):
    """Ruft Claude auf; lehnt das Modell ab, springt serverseitig ein
    Ersatzmodell ein. Liefert den Antworttext."""
    message = client.beta.messages.create(
        model=MODEL,
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},
        **kwargs,
    )
    if message.stop_reason == "refusal":
        raise RuntimeError("Anfrage vom Modell abgelehnt")
    if message.stop_reason == "max_tokens":
        raise RuntimeError("Antwort am Token-Limit abgeschnitten")
    text_parts = [block.text for block in message.content if block.type == "text"]
    return "\n".join(text_parts).strip()


def summarize_email(client, subject, sender, body):
    user_content = f"Absender: {sender}\nBetreff: {subject}\n\nInhalt:\n{body[:SUMMARY_INPUT_CHARS]}"

    return create_message(
        client,
        max_tokens=4000,
        output_config={"effort": "low"},
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    )


def build_market_report(client, emails):
    """Fasst alle Newsletter zu einem Marktbericht zusammen: Hauptquellen im
    Volltext, alle anderen als Kurzfassung."""
    primary, others = [], []
    for e in emails:
        if e["source"]:
            primary.append(
                f'<newsletter quelle="{e["source"]}" absender="{e["sender"]}" '
                f'betreff="{e["subject"]}" datum="{e["date"]}">\n'
                f'{e["body"][:REPORT_INPUT_CHARS]}\n</newsletter>'
            )
        else:
            others.append(
                f'<kurzfassung absender="{e["sender"]}" betreff="{e["subject"]}">\n'
                f'{e["summary"]}\n</kurzfassung>'
            )

    user_content = (
        "<hauptquellen>\n" + ("\n\n".join(primary) or "(heute keine)") + "\n</hauptquellen>\n\n"
        "<weitere_mails>\n" + ("\n\n".join(others) or "(heute keine)") + "\n</weitere_mails>"
    )

    text = create_message(
        client,
        max_tokens=16000,
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": REPORT_SCHEMA},
        },
        system=REPORT_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    return json.loads(text)


STYLE = """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: #f5f3ef;
      color: #2c2c2c;
      padding: 40px 20px;
      max-width: 860px;
      margin: 0 auto;
    }
    header {
      margin-bottom: 36px;
      border-bottom: 2px solid #b5a98a;
      padding-bottom: 16px;
    }
    header h1 {
      font-size: 1.6rem;
      font-weight: 600;
      color: #2c2c2c;
      letter-spacing: 0.01em;
    }
    header p {
      font-size: 0.85rem;
      color: #7a7060;
      margin-top: 4px;
    }
    .mail-card {
      background: #fff;
      border: 1px solid #e0d9cc;
      border-radius: 8px;
      margin-bottom: 20px;
      overflow: hidden;
    }
    .mail-header {
      background: #f0ece4;
      padding: 14px 20px;
      border-bottom: 1px solid #e0d9cc;
    }
    .mail-subject {
      display: block;
      font-weight: 600;
      font-size: 1rem;
      color: #2c2c2c;
    }
    .mail-meta {
      display: block;
      font-size: 0.78rem;
      color: #7a7060;
      margin-top: 4px;
    }
    .mail-body {
      padding: 16px 20px;
    }
    ul {
      padding-left: 20px;
      margin-bottom: 12px;
    }
    li {
      font-size: 0.92rem;
      line-height: 1.6;
      color: #3a3a3a;
      margin-bottom: 4px;
    }
    .links {
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid #e8e3da;
    }
    .links strong {
      font-size: 0.82rem;
      color: #7a7060;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .links ul {
      margin-top: 6px;
    }
    .links li {
      font-size: 0.85rem;
    }
    .links a {
      color: #6b8a6b;
      text-decoration: none;
    }
    .links a:hover {
      text-decoration: underline;
    }
    footer {
      margin-top: 40px;
      font-size: 0.78rem;
      color: #9a9080;
      text-align: center;
    }
    .quelle {
      font-size: 0.78rem;
      color: #9a9080;
      white-space: nowrap;
    }
    .highlight {
      background: #fbf8f1;
      border-color: #b5a98a;
    }
"""


def build_html(emails_with_summaries, generated_at):
    items_html = ""

    for e in emails_with_summaries:
        lines = [l.strip() for l in e["summary"].split("\n") if l.strip()]
        bullets_html = "<ul>\n"
        for line in lines:
            clean = re.sub(r"^[-•*]\s*", "", line)
            bullets_html += f"  <li>{html.escape(clean)}</li>\n"
        bullets_html += "</ul>"

        links_html = ""
        if e["links"]:
            links_html = '<div class="links"><strong>Links:</strong><ul>\n'
            for text, href in e["links"]:
                links_html += f'  <li><a href="{html.escape(href)}" target="_blank">{html.escape(text)}</a></li>\n'
            links_html += "</ul></div>"

        items_html += f"""
<div class="mail-card">
  <div class="mail-header">
    <span class="mail-subject">{html.escape(e["subject"])}</span>
    <span class="mail-meta">{html.escape(e["sender"])} &nbsp;·&nbsp; {html.escape(e["date"])}</span>
  </div>
  <div class="mail-body">
    {bullets_html}
    {links_html}
  </div>
</div>
"""

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Daily Mail Brief – {generated_at}</title>
  <style>
{STYLE}
  </style>
</head>
<body>
  <header>
    <h1>Daily Mail Brief</h1>
    <p>Generiert am {generated_at} &nbsp;·&nbsp; {len(emails_with_summaries)} E-Mails der letzten 24 Stunden</p>
  </header>

  {items_html if items_html else '<p style="color:#9a9080;text-align:center;padding:40px 0;">Keine neuen E-Mails in den letzten 24 Stunden.</p>'}

  <footer>Erstellt mit Claude API &nbsp;·&nbsp; newsletter@raab.koeln</footer>
</body>
</html>"""


def _points_html(points):
    items = "".join(
        f'  <li>{html.escape(p["text"])} <span class="quelle">({html.escape(p["quelle"])})</span></li>\n'
        for p in points
    )
    return f"<ul>\n{items}</ul>"


def _card_html(title, points, extra_class=""):
    return f"""
<div class="mail-card {extra_class}">
  <div class="mail-header">
    <span class="mail-subject">{html.escape(title)}</span>
  </div>
  <div class="mail-body">
    {_points_html(points)}
  </div>
</div>
"""


def build_report_html(report, emails, generated_at):
    cards = _card_html("Das Wichtigste in Kürze", report["kurzfassung"], "highlight")
    for section in report["abschnitte"]:
        if section["punkte"]:
            cards += _card_html(section["titel"], section["punkte"])
    if report["weitere_themen"]:
        cards += _card_html("Weitere Themen", report["weitere_themen"])

    sources = sorted({e["source"] for e in emails if e["source"]})
    sources_text = ", ".join(sources) if sources else "keine Hauptquellen"

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Marktbericht – {generated_at}</title>
  <style>
{STYLE}
  </style>
</head>
<body>
  <header>
    <h1>Marktbericht</h1>
    <p>Generiert am {generated_at} &nbsp;·&nbsp; aus {len(emails)} Newslettern der letzten 24 Stunden &nbsp;·&nbsp; Hauptquellen: {html.escape(sources_text)}</p>
  </header>

  {cards}

  <footer>Erstellt mit Claude API &nbsp;·&nbsp; newsletter@raab.koeln</footer>
</body>
</html>"""


def main():
    # Mehr Wiederholungen als der SDK-Standard (2): die große Berichts-Anfrage
    # brach bei wackeliger Verbindung sonst mit "Connection error" ab.
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY, max_retries=5)

    # Alte Ausgaben entfernen: Der Workflow verschickt nur, was dieser Lauf erzeugt.
    for path in (OUTPUT_FILE, REPORT_FILE):
        if os.path.exists(path):
            os.remove(path)

    emails = fetch_recent_emails()

    if not emails:
        print("Keine Mails gefunden. Skript beendet.")
        return

    emails_with_summaries = []
    for i, e in enumerate(emails, 1):
        print(f"[{i}/{len(emails)}] Zusammenfassung: {e['subject'][:60]}...")
        try:
            summary = summarize_email(client, e["subject"], e["sender"], e["body"])
        except Exception as exc:
            print(f"  ! Zusammenfassung fehlgeschlagen: {exc}")
            summary = "- (Zusammenfassung fehlgeschlagen)"
        emails_with_summaries.append({**e, "summary": summary})

    generated_at = datetime.datetime.now(TZ).strftime("%d.%m.%Y %H:%M")
    html_content = build_html(emails_with_summaries, generated_at)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"\nFertig → {OUTPUT_FILE}")

    # Ein Fehler beim Marktbericht soll den Brief nicht verhindern.
    print("Erstelle Marktbericht...")
    try:
        report = build_market_report(client, emails_with_summaries)
    except Exception as exc:
        print(f"  ! Marktbericht fehlgeschlagen: {exc}")
        return
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(build_report_html(report, emails_with_summaries, generated_at))
    print(f"Fertig → {REPORT_FILE}")


if __name__ == "__main__":
    main()
