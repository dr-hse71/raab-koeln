import os
import re
from datetime import datetime
from googleapiclient.discovery import build
import anthropic

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CHANNEL_HANDLE = "RiskReversalMedia"

def get_channel_id(youtube):
    response = youtube.channels().list(
        part="id",
        forHandle=CHANNEL_HANDLE
    ).execute()
    return response["items"][0]["id"]

def get_latest_video(youtube, channel_id):
    response = youtube.search().list(
        part="snippet",
        channelId=channel_id,
        order="date",
        maxResults=5,
        type="video",
        q="MRKT Call"
    ).execute()

    for item in response["items"]:
        title = item["snippet"]["title"]
        if any(word in title for word in ["MRKT", "Market", "Tariff", "Stock", "Fed", "Trade"]):
            video_id = item["id"]["videoId"]
            published = item["snippet"]["publishedAt"]
            return video_id, title, published

    item = response["items"][0]
    return item["id"]["videoId"], item["snippet"]["title"], item["snippet"]["publishedAt"]

def get_video_description(youtube, video_id):
    response = youtube.videos().list(
        part="snippet",
        id=video_id
    ).execute()
    if response["items"]:
        return response["items"][0]["snippet"]["description"]
    return ""

def summarize_with_claude(title, description, video_url):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Du bist ein professioneller Finanzanalyst. Basierend auf dem Titel und der Beschreibung der folgenden MRKT Call Episode, erstelle eine ausführliche und strukturierte Zusammenfassung auf Deutsch.

TITEL: {title}
VIDEO URL: {video_url}

BESCHREIBUNG:
{description}

Erstelle eine professionelle Zusammenfassung mit folgenden Abschnitten als Fließtext:

**Überblick**
Was ist das zentrale Thema dieser Episode?

**Marktlage & Sentiment**
Wie beurteilen die Hosts die aktuelle Marktlage?

**Hauptthemen**
Welche konkreten Themen werden besprochen?

**Aktien & Assets**
Welche Werte oder Sektoren werden erwähnt?

**Trade Ideas & Empfehlungen**
Welche Handelsideen werden genannt?

**Ausblick**
Was erwarten die Hosts für die kommenden Tage?

Schreibe professionell auf Deutsch. Behalte englische Fachbegriffe bei."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

def create_html(title, published, summary, video_url):
    date_obj = datetime.fromisoformat(published.replace("Z", "+00:00"))
    date_str = date_obj.strftime("%d. %B %Y")

    lines = summary.split("\n")
    html_parts = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("**") and line.endswith("**"):
            heading = line.replace("**", "")
            html_parts.append(f'<div class="section-label">{heading}</div>')
        else:
            line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
            html_parts.append(f'<p>{line}</p>')

    summary_html = "\n".join(html_parts)

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MRKT Call — {date_str}</title>
    <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;1,300&family=Jost:wght@200;300;400&display=swap" rel="stylesheet">
    <style>
        *, *::before, *::after {{ margin: 0; padding: 0; box-sizing: border-box; }}

        :root {{
            --ink: #181818;
            --muted: #999;
            --faint: #ccc;
            --accent: #b8966e;
            --bg: #f9f8f6;
            --line: #e9e5e0;
        }}

        body {{
            font-family: 'Jost', sans-serif;
            font-weight: 300;
            background: var(--bg);
            color: var(--ink);
            min-height: 100vh;
        }}

        header {{
            padding: 2.5rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--line);
        }}

        .back-link {{
            font-size: 0.72rem;
            letter-spacing: 0.18em;
            text-transform: uppercase;
            color: #888;
            text-decoration: none;
            transition: color 0.2s;
        }}
        .back-link:hover {{ color: var(--accent); }}

        .brand {{
            font-size: 0.72rem;
            letter-spacing: 0.18em;
            text-transform: uppercase;
            color: #aaa;
        }}

        main {{
            max-width: 680px;
            margin: 0 auto;
            padding: 4rem 2rem 6rem;
        }}

        .meta {{
            font-size: 0.72rem;
            letter-spacing: 0.18em;
            text-transform: uppercase;
            color: #888;
            margin-bottom: 1rem;
        }}

        h1 {{
            font-family: 'Cormorant Garamond', serif;
            font-size: clamp(1.8rem, 5vw, 2.8rem);
            font-weight: 300;
            line-height: 1.2;
            color: var(--ink);
            margin-bottom: 0.75rem;
        }}

        .divider {{
            width: 28px;
            height: 1px;
            background: var(--accent);
            margin: 2rem 0;
        }}

        .video-link {{
            display: inline-block;
            font-size: 0.72rem;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: var(--accent);
            text-decoration: none;
            border-bottom: 1px solid var(--accent);
            padding-bottom: 0.1rem;
            margin-bottom: 3rem;
            transition: opacity 0.2s;
        }}
        .video-link:hover {{ opacity: 0.6; }}

        .section-label {{
            font-size: 0.72rem;
            letter-spacing: 0.18em;
            text-transform: uppercase;
            color: #888;
            margin: 2.5rem 0 0.75rem;
            border-top: 1px solid var(--line);
            padding-top: 1.5rem;
        }}
        .section-label:first-child {{ border-top: none; padding-top: 0; }}

        .summary p {{
            font-size: 0.95rem;
            line-height: 1.85;
            color: #444;
            margin-bottom: 0.6rem;
        }}

        .summary strong {{
            font-weight: 400;
            color: var(--ink);
        }}

        footer {{
            text-align: center;
            padding: 2.5rem;
            border-top: 1px solid var(--line);
            font-size: 0.72rem;
            letter-spacing: 0.12em;
            color: #bbb;
        }}
    </style>
</head>
<body>
    <header>
        <a href="/" class="back-link">← raab.koeln</a>
        <span class="brand">MRKT Call</span>
    </header>

    <main>
        <div class="meta">{date_str}</div>
        <h1>{title}</h1>
        <a href="{video_url}" target="_blank" class="video-link">▶ Video ansehen</a>
        <div class="divider"></div>
        <div class="summary">
            {summary_html}
        </div>
    </main>

    <footer>
        KI-generierte Zusammenfassung &nbsp;·&nbsp; {datetime.now().strftime("%d.%m.%Y")} &nbsp;·&nbsp; raab.koeln
    </footer>
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
