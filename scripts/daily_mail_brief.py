import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
import anthropic
import os
import datetime
import html
import re
from bs4 import BeautifulSoup

# ── Konfiguration ──────────────────────────────────────────────
IMAP_HOST = "imap.netcologne.de"
IMAP_PORT = 993
IMAP_USER = "daniel@raab.koeln"
IMAP_PASS = os.environ["NETCOLOGNE_PASSWORD"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
OUTPUT_FILE = "output/daily_brief.html"
HOURS_BACK = 24
# ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Du bist ein effizienter E-Mail-Assistent. Fasse die folgende E-Mail prägnant zusammen.

Erstelle eine Zusammenfassung mit:
- 3-6 Bullet Points (die wichtigsten Informationen, Kerninhalte, Handlungsaufforderungen)
- Falls es ein Newsletter mit mehreren Artikeln ist: ein Bullet Point pro Artikel
- Maximal 1-2 Sätze pro Bullet Point
- Auf Deutsch, auch wenn die Mail auf Englisch ist

Antworte NUR mit den Bullet Points, keine Einleitung, kein Fazit."""


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

    return body.strip()[:4000]


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
                    if href.startswith("http") and text and len(text) > 3:
                        links.append((text, href))
    seen = set()
    unique = []
    for text, href in links:
        if href not in seen:
            seen.add(href)
            unique.append((text, href))
    return unique[:10]


def fetch_recent_emails():
    print(f"Verbinde mit {IMAP_HOST}...")
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    mail.login(IMAP_USER, IMAP_PASS)
    mail.select("INBOX")

    since = (datetime.datetime.now() - datetime.timedelta(hours=HOURS_BACK)).strftime("%d-%b-%Y")
    _, data = mail.search(None, f'(SINCE "{since}")')

    mail_ids = data[0].split()
    print(f"{len(mail_ids)} Mails der letzten 24h gefunden.")

    emails = []
    for mid in mail_ids:
        _, msg_data = mail.fetch(mid, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        subject = decode_str(msg.get("Subject", "(kein Betreff)"))
        sender = decode_str(msg.get("From", ""))
        date_str = msg.get("Date", "")
        try:
            date = parsedate_to_datetime(date_str).strftime("%d.%m.%Y %H:%M")
        except Exception:
            date = date_str

        body = extract_body(msg)
        links = extract_links(msg)

        emails.append({
            "subject": subject,
            "sender": sender,
            "date": date,
            "body": body,
            "links": links,
        })

    mail.logout()
    return list(reversed(emails))


def summarize_email(client, subject, sender, body):
    user_content = f"Absender: {sender}\nBetreff: {subject}\n\nInhalt:\n{body}"

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    )
    return message.content[0].text.strip()


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
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: #f5f3ef;
      color: #2c2c2c;
      padding: 40px 20px;
      max-width: 860px;
      margin: 0 auto;
    }}
    header {{
      margin-bottom: 36px;
      border-bottom: 2px solid #b5a98a;
      padding-bottom: 16px;
    }}
    header h1 {{
      font-size: 1.6rem;
      font-weight: 600;
      color: #2c2c2c;
      letter-spacing: 0.01em;
    }}
    header p {{
      font-size: 0.85rem;
      color: #7a7060;
      margin-top: 4px;
    }}
    .mail-card {{
      background: #fff;
      border: 1px solid #e0d9cc;
      border-radius: 8px;
      margin-bottom: 20px;
      overflow: hidden;
    }}
    .mail-header {{
      background: #f0ece4;
      padding: 14px 20px;
      border-bottom: 1px solid #e0d9cc;
    }}
    .mail-subject {{
      display: block;
      font-weight: 600;
      font-size: 1rem;
      color: #2c2c2c;
    }}
    .mail-meta {{
      display: block;
      font-size: 0.78rem;
      color: #7a7060;
      margin-top: 4px;
    }}
    .mail-body {{
      padding: 16px 20px;
    }}
    ul {{
      padding-left: 20px;
      margin-bottom: 12px;
    }}
    li {{
      font-size: 0.92rem;
      line-height: 1.6;
      color: #3a3a3a;
      margin-bottom: 4px;
    }}
    .links {{
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid #e8e3da;
    }}
    .links strong {{
      font-size: 0.82rem;
      color: #7a7060;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    .links ul {{
      margin-top: 6px;
    }}
    .links li {{
      font-size: 0.85rem;
    }}
    .links a {{
      color: #6b8a6b;
      text-decoration: none;
    }}
    .links a:hover {{
      text-decoration: underline;
    }}
    footer {{
      margin-top: 40px;
      font-size: 0.78rem;
      color: #9a9080;
      text-align: center;
    }}
  </style>
</head>
<body>
  <header>
    <h1>Daily Mail Brief</h1>
    <p>Generiert am {generated_at} &nbsp;·&nbsp; {len(emails_with_summaries)} E-Mails der letzten 24 Stunden</p>
  </header>

  {items_html if items_html else '<p style="color:#9a9080;text-align:center;padding:40px 0;">Keine neuen E-Mails in den letzten 24 Stunden.</p>'}

  <footer>Erstellt mit Claude API &nbsp;·&nbsp; daniel@raab.koeln</footer>
</body>
</html>"""


def main():
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    emails = fetch_recent_emails()

    if not emails:
        print("Keine Mails gefunden. Skript beendet.")
        return

    emails_with_summaries = []
    for i, e in enumerate(emails, 1):
        print(f"[{i}/{len(emails)}] Zusammenfassung: {e['subject'][:60]}...")
        summary = summarize_email(client, e["subject"], e["sender"], e["body"])
        emails_with_summaries.append({**e, "summary": summary})

    generated_at = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    html_content = build_html(emails_with_summaries, generated_at)

    os.makedirs("output", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\nFertig → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
