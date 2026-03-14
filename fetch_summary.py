import os
import json
import re
from datetime import datetime
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
import anthropic

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CHANNEL_HANDLE = "RiskReversalMedia"

def get_latest_video():
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    
    # Get channel ID from handle
    response = youtube.search().list(
        part="snippet",
        q="MRKT Call",
        channelId=get_channel_id(youtube),
        order="date",
        maxResults=1,
        type="video"
    ).execute()
    
    if not response["items"]:
        raise Exception("Kein Video gefunden")
    
    item = response["items"][0]
    video_id = item["id"]["videoId"]
    title = item["snippet"]["title"]
    published = item["snippet"]["publishedAt"]
    
    return video_id, title, published

def get_channel_id(youtube):
    response = youtube.channels().list(
        part="id",
        forHandle=CHANNEL_HANDLE
    ).execute()
    return response["items"][0]["id"]

def get_transcript(video_id):
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
        full_text = " ".join([entry["text"] for entry in transcript_list])
        return full_text
    except Exception as e:
        raise Exception(f"Transcript nicht verfügbar: {e}")

def summarize(title, transcript):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    prompt = f"""Du bist ein professioneller Finanzanalyst. Fasse das folgende Transkript der MRKT Call Episode "{title}" auf Deutsch zusammen.

Erstelle eine strukturierte, vollständige Zusammenfassung mit folgenden Abschnitten:

1. **Überblick** — Kurze Einleitung was in dieser Episode besprochen wurde (2-3 Sätze)
2. **Marktlage** — Aktuelle Einschätzung der Marktlage und Stimmung
3. **Hauptthemen** — Die wichtigsten besprochenen Themen (als Fließtext, nicht als Liste)
4. **Aktien & Assets** — Konkret genannte Werte, Sektoren oder Assets und was darüber gesagt wurde
5. **Trade Ideas** — Konkrete Handelsideen oder Empfehlungen falls genannt
6. **Ausblick** — Was die Hosts für die nächsten Tage/Wochen erwarten

Schreibe professionell, präzise und auf Deutsch. Behalte wichtige englische Fachbegriffe bei.

TRANSKRIPT:
{transcript[:12000]}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    return message.content[0].text

def create_html(title, published, summary):
    date_obj = datetime.fromisoformat(published.replace("Z", "+00:00"))
    date_str = date_obj.strftime("%d. %B %Y")
    
    # Convert markdown bold to HTML
    summary_html = summary.replace("**", "<strong>", 1)
    while "**" in summary_html:
        summary_html = summary_html.replace("**", "</strong>", 1)
        if "**" in summary_html:
            summary_html = summary_html.replace("**", "<strong>", 1)
    
    # Convert newlines to paragraphs
    paragraphs = summary_html.split("\n\n")
    summary_html = "".join([f"<p>{p.strip()}</p>" for p in paragraphs if p.strip()])
    
    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MRKT Call — {date_str}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            background: #0a0e1a;
            color: #e2e8f0;
            font-family: 'Georgia', serif;
            min-height: 100vh;
        }}
        
        header {{
            background: #0d1117;
            border-bottom: 1px solid #1e2d40;
            padding: 2rem 0;
        }}
        
        .header-inner {{
            max-width: 860px;
            margin: 0 auto;
            padding: 0 2rem;
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
        }}
        
        .brand {{
            font-family: 'Georgia', serif;
            font-size: 0.75rem;
            letter-spacing: 0.2em;
            text-transform: uppercase;
            color: #4a9eff;
        }}
        
        .back-link {{
            font-size: 0.8rem;
            color: #4a6080;
            text-decoration: none;
            letter-spacing: 0.05em;
        }}
        
        .back-link:hover {{ color: #4a9eff; }}
        
        main {{
            max-width: 860px;
            margin: 0 auto;
            padding: 3rem 2rem 6rem;
        }}
        
        .meta {{
            font-size: 0.75rem;
            letter-spacing: 0.15em;
            text-transform: uppercase;
            color: #4a6080;
            margin-bottom: 1rem;
        }}
        
        h1 {{
            font-size: 1.9rem;
            font-weight: normal;
            line-height: 1.3;
            color: #f0f4f8;
            margin-bottom: 2.5rem;
            border-bottom: 1px solid #1e2d40;
            padding-bottom: 2rem;
        }}
        
        .summary p {{
            font-size: 1rem;
            line-height: 1.85;
            color: #c8d4e0;
            margin-bottom: 1.2rem;
        }}
        
        .summary strong {{
            color: #4a9eff;
            font-weight: normal;
            font-style: normal;
        }}
        
        footer {{
            max-width: 860px;
            margin: 0 auto;
            padding: 2rem;
            border-top: 1px solid #1e2d40;
            font-size: 0.75rem;
            color: #2a3a4a;
            letter-spacing: 0.05em;
        }}
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
        <div class="summary">
            {summary_html}
        </div>
    </main>
    
    <footer>
        Automatisch generierte Zusammenfassung · {datetime.now().strftime("%d.%m.%Y %H:%M")} · raab.koeln
    </footer>
</body>
</html>"""
    
    return html

def main():
    print("Hole neuestes MRKT Call Video...")
    video_id, title, published = get_latest_video()
    print(f"Gefunden: {title}")
    
    print("Hole Transcript...")
    transcript = get_transcript(video_id)
    print(f"Transcript: {len(transcript)} Zeichen")
    
    print("Erstelle Zusammenfassung mit Claude...")
    summary = summarize(title, transcript)
    
    print("Erstelle HTML...")
    html = create_html(title, published, summary)
    
    with open("marktcall.html", "w", encoding="utf-8") as f:
        f.write(html)
    
    print("Fertig! marktcall.html erstellt.")

if __name__ == "__main__":
    main()
