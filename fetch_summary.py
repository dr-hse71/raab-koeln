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
            html_parts.append(f'<h2>{heading}</h2>')
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
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ background: #0a0e1a; color: #e2e8f0; font-family: 'Georgia', serif; min-height: 100vh; }}
        header {{ background: #0d1117; border-bottom: 1px solid #1e2d40; padding: 1.5rem 0; }}
        .header-inner {{ max-width: 860px; margin: 0 auto; padding: 0 2rem; display: flex; justify-content: space-between; align-items: center; }}
        .brand {{ font-family: sans-serif; font-size: 0.7rem; letter-spacing: 0.2em; text-transform: uppercase; color: #4a9eff; }}
        .back-link {{ font-size: 0.8rem; color: #4a6080; text-decoration: none; }}
        .back-link:hover {{ color: #4a9eff; }}
        main {{ max-width: 860px; margin: 0 auto; padding: 3rem 2rem 5rem; }}
        .meta {{ font-size: 0.7rem; letter-spacing: 0.15em; text-transform: uppercase; color: #4a6080; margin-bottom: 0.75rem; font-family: sans-serif; }}
        h1 {{ font-size: 2rem; font-weight: normal; line-height: 1.3; color: #f0f4f8; margin-bottom: 1rem; }}
        .video-link {{ display: inline-block; font-size: 0.75rem; font-family: sans-serif; color: #4a9eff; text-decoration: none; border: 1px solid #1e3a5f; padding: 0.4rem 0.9rem; border-radius: 3px; margin-bottom: 2.5rem; }}
        .video-link:hover {{ background: #1e3a5f; }}
        hr {{ border: none; border-top: 1px solid #1e2d40; margin-bottom: 2.5rem; }}
        .summary h2 {{ font-size: 0.7rem; font-family: sans-serif; letter-spacing: 0.18em; text-transform: uppercase; color: #4a9eff; font-weight: normal; margin: 2rem 0 0.75rem; }}
        .summary p {{ font-size: 1rem; line-height: 1.85; color: #c8d4e0; margin-bottom: 0.5rem; }}
        footer {{ max-width: 860px; margin: 0 auto; padding: 1.5rem 2rem; border-top: 1px solid #1e2d40; font-size: 0.7rem; font-family: sans-serif; color: #2a3a4a; }}
    </style>
</head>
<body>
    <header>
        <div class="header-inner">
            <span class="brand">MRKT Call · Risk Reversal Media</span>
            <a href="/" class="back-link">← raab.koeln</a>
        </div>
    </header>
    <main>
        <div class="meta">{date_str}</div>
        <h1>{title}</h1>
        <a href="{video_url}" target="_blank" class="video-link">▶ Video ansehen</a>
        <hr>
        <div class="summary">{summary_html}</div>
    </main>
    <footer>KI-generierte Zusammenfassung · {datetime.now().strftime("%d.%m.%Y %H:%M")} · raab.koeln</footer>
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
