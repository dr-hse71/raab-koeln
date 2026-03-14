import os
import re
import json
from datetime import datetime
from googleapiclient.discovery import build
import anthropic

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CHANNEL_HANDLE = "RiskReversalMedia"  # v2 dashboard layout

def get_channel_id(youtube):
    response = youtube.channels().list(part="id", forHandle=CHANNEL_HANDLE).execute()
    return response["items"][0]["id"]

def get_latest_video(youtube, channel_id):
    response = youtube.search().list(
        part="snippet", channelId=channel_id, order="date",
        maxResults=5, type="video", q="MRKT Call"
    ).execute()
    for item in response["items"]:
        title = item["snippet"]["title"]
        if any(w in title for w in ["MRKT", "Market", "Tariff", "Stock", "Fed", "Trade"]):
            return item["id"]["videoId"], title, item["snippet"]["publishedAt"]
    item = response["items"][0]
    return item["id"]["videoId"], item["snippet"]["title"], item["snippet"]["publishedAt"]

def get_video_description(youtube, video_id):
    response = youtube.videos().list(part="snippet", id=video_id).execute()
    if response["items"]:
        return response["items"][0]["snippet"]["description"]
    return ""

def summarize_with_claude(title, description, video_url):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""Du bist ein professioneller Finanzanalyst bei einer deutschen Privatbank. Analysiere die folgende MRKT Call Episode und erstelle eine faktenreiche Zusammenfassung auf Deutsch.

TITEL: {title}
VIDEO URL: {video_url}

BESCHREIBUNG:
{description}

Erstelle die Zusammenfassung als JSON mit exakt dieser Struktur:
{{
  "ueberblick": "2-3 praegnante Saetze zum zentralen Thema der Episode",
  "marktlage": [
    "Stichpunkt mit konkreter Zahl oder Fakt",
    "weitere Stichpunkte..."
  ],
  "hauptthemen": [
    {{"titel": "Thema 1", "punkte": ["Stichpunkt mit Fakten", "Stichpunkt"]}},
    {{"titel": "Thema 2", "punkte": ["Stichpunkt", "Stichpunkt"]}}
  ],
  "aktien_assets": [
    {{"name": "Ticker/Name", "punkte": ["Konkrete Aussage", "Kurs/Ziel falls genannt"]}}
  ],
  "trade_ideas": [
    "Konkrete Handelsidee mit Begruendung"
  ],
  "ausblick": [
    "Konkreter Ausblick-Punkt"
  ]
}}

Wichtig:
- Nutze alle verfuegbaren Informationen aus Titel und Beschreibung
- Falls die Beschreibung kurz ist, leite Themen aus dem Titel ab und ergaenze mit plausiblem Marktkontext
- Moeglichst konkrete Zahlen, Kursziele, Prozentangaben wo vorhanden
- Stichworte statt langer Saetze
- Englische Fachbegriffe und Ticker beibehalten
- Felder niemals leer lassen — immer mindestens 2-3 Punkte pro Abschnitt
- Nur JSON zurueckgeben, kein weiterer Text"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

def li(items):
    return "\n".join([f"<li>{i}</li>" for i in items])

def create_html(title, published, summary, video_url):
    date_obj = datetime.fromisoformat(published.replace("Z", "+00:00"))
    date_str = date_obj.strftime("%d. %B %Y")
    now_str = datetime.now().strftime("%d.%m.%Y")

    clean = re.sub(r"```json|```", "", summary.strip()).strip()
    try:
        data = json.loads(clean)
    except Exception:
        data = {"ueberblick": summary, "marktlage": [], "hauptthemen": [], "aktien_assets": [], "trade_ideas": [], "ausblick": []}

    # Hauptthemen Tabs
    themen_tabs = ""
    themen_panels = ""
    for i, t in enumerate(data.get("hauptthemen", [])):
        active = "active" if i == 0 else ""
        themen_tabs += f'<button class="tab-btn {active}" onclick="switchTab(this,\'thema-{i}\')">{t["titel"]}</button>\n'
        themen_panels += f'<div id="thema-{i}" class="tab-panel {active}"><ul>{li(t["punkte"])}</ul></div>\n'

    # Aktien Tabs
    aktien_tabs = ""
    aktien_panels = ""
    for i, a in enumerate(data.get("aktien_assets", [])):
        active = "active" if i == 0 else ""
        aktien_tabs += f'<button class="tab-btn {active}" onclick="switchTab(this,\'aktie-{i}\')">{a["name"]}</button>\n'
        aktien_panels += f'<div id="aktie-{i}" class="tab-panel {active}"><ul>{li(a["punkte"])}</ul></div>\n'

    ueberblick = data.get("ueberblick", "")
    marktlage_html = li(data.get("marktlage", []))
    trade_html = li(data.get("trade_ideas", []))
    ausblick_html = li(data.get("ausblick", []))

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MRKT Call &mdash; {date_str}</title>
    <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;1,300&family=Jost:wght@200;300;400&display=swap" rel="stylesheet">
    <style>
        *, *::before, *::after {{ margin: 0; padding: 0; box-sizing: border-box; }}
        :root {{ --ink: #181818; --accent: #b8966e; --bg: #f9f8f6; --line: #e9e5e0; }}
        body {{ font-family: 'Jost', sans-serif; font-weight: 300; background: var(--bg); color: var(--ink); min-height: 100vh; }}
        header {{ padding: 2.5rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--line); }}
        .back-link {{ font-size: 0.72rem; letter-spacing: 0.18em; text-transform: uppercase; color: #888; text-decoration: none; transition: color 0.2s; }}
        .back-link:hover {{ color: var(--accent); }}
        .brand {{ font-size: 0.72rem; letter-spacing: 0.18em; text-transform: uppercase; color: #aaa; }}
        main {{ max-width: 680px; margin: 0 auto; padding: 4rem 2rem 6rem; }}
        .meta {{ font-size: 0.72rem; letter-spacing: 0.18em; text-transform: uppercase; color: #888; margin-bottom: 1rem; }}
        h1 {{ font-family: 'Cormorant Garamond', serif; font-size: clamp(1.8rem, 5vw, 2.8rem); font-weight: 300; line-height: 1.2; color: var(--ink); margin-bottom: 0.75rem; }}
        .divider {{ width: 28px; height: 1px; background: var(--accent); margin: 2rem 0; }}
        .video-link {{ display: inline-block; font-size: 0.72rem; letter-spacing: 0.12em; text-transform: uppercase; color: var(--accent); text-decoration: none; border-bottom: 1px solid var(--accent); padding-bottom: 0.1rem; margin-bottom: 2rem; transition: opacity 0.2s; }}
        .video-link:hover {{ opacity: 0.6; }}
        .ueberblick {{ font-size: 1.05rem; line-height: 1.8; color: #555; margin-bottom: 0.5rem; }}
        .section-label {{ font-size: 0.72rem; letter-spacing: 0.18em; text-transform: uppercase; color: #888; margin: 2.5rem 0 0.9rem; border-top: 1px solid var(--line); padding-top: 1.5rem; }}
        ul.bullet-list {{ list-style: none; padding: 0; }}
        ul.bullet-list li {{ font-size: 1.05rem; line-height: 1.7; color: #444; padding: 0.4rem 0 0.4rem 1.2rem; border-bottom: 1px solid var(--line); position: relative; }}
        ul.bullet-list li:last-child {{ border-bottom: none; }}
        ul.bullet-list li::before {{ content: '\2013'; position: absolute; left: 0; color: var(--accent); }}
        .tab-bar {{ display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1.25rem; }}
        .tab-btn {{ font-family: 'Jost', sans-serif; font-size: 0.72rem; font-weight: 300; letter-spacing: 0.12em; text-transform: uppercase; color: #888; background: none; border: 1px solid var(--line); padding: 0.35rem 0.9rem; cursor: pointer; transition: all 0.2s; }}
        .tab-btn:hover, .tab-btn.active {{ border-color: var(--accent); color: var(--accent); }}
        .tab-panel {{ display: none; }}
        .tab-panel.active {{ display: block; }}
        .tab-content ul {{ list-style: none; padding: 0; }}
        .tab-content li {{ font-size: 1.05rem; line-height: 1.7; color: #444; padding: 0.4rem 0 0.4rem 1.2rem; border-bottom: 1px solid var(--line); position: relative; }}
        .tab-content li:last-child {{ border-bottom: none; }}
        .tab-content li::before {{ content: '\2013'; position: absolute; left: 0; color: var(--accent); }}
        footer {{ text-align: center; padding: 2.5rem; border-top: 1px solid var(--line); font-size: 0.72rem; letter-spacing: 0.12em; color: #bbb; }}
    </style>
</head>
<body>
    <header>
        <a href="/" class="back-link">&larr; raab.koeln</a>
        <span class="brand">MRKT Call</span>
    </header>
    <main>
        <div class="meta">{date_str}</div>
        <h1>{title}</h1>
        <a href="{video_url}" target="_blank" class="video-link">&#9654; Video ansehen</a>
        <div class="divider"></div>
        <p class="ueberblick">{ueberblick}</p>

        <div class="section-label">Marktlage</div>
        <ul class="bullet-list">{marktlage_html}</ul>

        <div class="section-label">Hauptthemen</div>
        <div class="tab-bar">{themen_tabs}</div>
        <div class="tab-content">{themen_panels}</div>

        <div class="section-label">Aktien &amp; Assets</div>
        <div class="tab-bar">{aktien_tabs}</div>
        <div class="tab-content">{aktien_panels}</div>

        <div class="section-label">Trade Ideas</div>
        <ul class="bullet-list">{trade_html}</ul>

        <div class="section-label">Ausblick</div>
        <ul class="bullet-list">{ausblick_html}</ul>
    </main>
    <footer>KI-generierte Zusammenfassung &nbsp;&middot;&nbsp; {now_str} &nbsp;&middot;&nbsp; raab.koeln</footer>
    <script>
    function switchTab(btn, panelId) {{
        const bar = btn.parentElement;
        bar.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const content = bar.nextElementSibling;
        content.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        document.getElementById(panelId).classList.add('active');
    }}
    </script>
</body>
</html>"""

def main():
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    print("Hole Channel ID...")
    channel_id = get_channel_id(youtube)
    print("Hole neuestes MRKT Call Video...")
    video_id, title, published = get_latest_video(youtube, channel_id)
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"Gefunden: {title}")
    print("Hole Video-Beschreibung...")
    description = get_video_description(youtube, video_id)
    print(f"Beschreibung: {len(description)} Zeichen")
    print("Erstelle Zusammenfassung mit Claude...")
    summary = summarize_with_claude(title, description, video_url)
    print("Erstelle HTML...")
    html = create_html(title, published, summary, video_url)
    with open("marktcall.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("Fertig! marktcall.html erstellt.")

if __name__ == "__main__":
    main()
