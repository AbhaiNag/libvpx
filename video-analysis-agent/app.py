import os
import base64
import subprocess
import tempfile
import json
import re
import time
from pathlib import Path
from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from flask_cors import CORS
import anthropic

app = Flask(__name__)
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024  # 512MB max upload

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

CUTTING_EDGE_TECH_2025 = """
2025 Cutting-Edge Technology Landscape:
- Generative AI & LLMs: Multimodal models, reasoning models (o-series), agentic AI systems, AI coding assistants
- Agentic AI: Autonomous AI agents, multi-agent orchestration, tool-use AI, AI workflows
- Edge AI: On-device inference, TinyML, neuromorphic chips, AI at the edge (Snapdragon, Apple Silicon)
- Quantum Computing: Error correction milestones (Google Willow), quantum advantage demonstrations
- Spatial Computing: Apple Vision Pro spatial UI paradigm, AR overlays, holographic displays
- Robotics: Boston Dynamics humanoids, Tesla Optimus, Figure 01 - physical AI revolution
- Synthetic Biology: CRISPR advances, AI-designed proteins (AlphaFold3), programmable cells
- Energy Tech: Solid-state batteries, nuclear fusion milestones (NIF, Commonwealth Fusion), green hydrogen
- Next-Gen Connectivity: 5G-Advanced, early 6G research, satellite mesh (Starlink v2)
- Advanced Materials: Metamaterials, 2D materials (graphene apps), self-healing materials
- Neuromorphic Computing: Intel Loihi 2, brain-inspired architectures
- Web3 & DePIN: Decentralized Physical Infrastructure, real-world asset tokenization
- Cybersecurity: Post-quantum cryptography (NIST standards), zero-trust architecture
- Digital Twins: Industrial metaverse, real-time simulation at scale
- Bioelectronics: BCI advances (Neuralink), implantable sensors, neural interfaces
"""

def get_video_duration(video_path):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
        capture_output=True, text=True, timeout=30
    )
    return float(result.stdout.strip() or 0)

def extract_video_frames(video_path, max_frames=14):
    frames = []
    duration = get_video_duration(video_path)

    if duration > 510:  # 8.5 min buffer
        raise ValueError(f"Video is {duration/60:.1f} minutes. Maximum allowed is 8 minutes.")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Sample frames evenly across the video
        interval = max(duration / max_frames, 10)
        output_pattern = os.path.join(tmpdir, 'frame_%04d.jpg')

        subprocess.run([
            'ffmpeg', '-i', video_path,
            '-vf', f'fps=1/{interval:.1f},scale=1280:-1',
            '-vframes', str(max_frames),
            '-q:v', '3',
            output_pattern
        ], capture_output=True, timeout=120)

        frame_files = sorted(Path(tmpdir).glob('frame_*.jpg'))
        for f in frame_files[:max_frames]:
            with open(f, 'rb') as img:
                frames.append(base64.b64encode(img.read()).decode('utf-8'))

    return frames, duration

def extract_audio_transcript(video_path):
    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, 'audio.wav')
        result = subprocess.run([
            'ffmpeg', '-i', video_path, '-vn',
            '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1',
            audio_path
        ], capture_output=True, timeout=120)

        if result.returncode != 0:
            return ""

        try:
            import whisper
            model = whisper.load_model("base")
            result = model.transcribe(audio_path)
            return result["text"]
        except ImportError:
            pass

        try:
            import speech_recognition as sr
            r = sr.Recognizer()
            with sr.AudioFile(audio_path) as source:
                audio = r.record(source)
            return r.recognize_google(audio)
        except Exception:
            return ""

def extract_pdf_text(pdf_path):
    text = ""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    text += f"\n--- Slide/Page {i+1} ---\n{page_text}"
        return text
    except Exception:
        pass

    try:
        import PyPDF2
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    text += f"\n--- Slide/Page {i+1} ---\n{page_text}"
    except Exception as e:
        text = f"[Could not extract PDF text: {e}]"

    return text

def build_analysis_prompt(frames, transcript, pdf_text, duration):
    content = []

    intro = f"I am analyzing a {duration/60:.1f}-minute video presentation for innovation potential."
    if frames:
        intro += f" I have extracted {len(frames)} key frames from the video for visual analysis."
    content.append({"type": "text", "text": intro})

    for i, frame_b64 in enumerate(frames):
        ts = (duration / len(frames)) * i
        content.append({"type": "text", "text": f"Frame {i+1} (at ~{ts:.0f}s / {ts/60:.1f}min):"})
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": frame_b64}
        })

    if transcript and len(transcript.strip()) > 30:
        content.append({
            "type": "text",
            "text": f"\n\n=== AUDIO TRANSCRIPT ===\n{transcript[:8000]}"
        })

    if pdf_text and len(pdf_text.strip()) > 20:
        content.append({
            "type": "text",
            "text": f"\n\n=== PRESENTATION SLIDES CONTENT ===\n{pdf_text[:8000]}"
        })

    content.append({
        "type": "text",
        "text": f"""
=== TECHNOLOGY REFERENCE (2025 State-of-the-Art) ===
{CUTTING_EDGE_TECH_2025}

=== ANALYSIS TASK ===
Based on ALL the above (video frames, transcript, presentation slides), perform a comprehensive innovation analysis.

Respond ONLY with valid JSON matching this exact schema:
{{
  "verdict": "QUALIFIED" or "NOT_QUALIFIED",
  "innovation_score": <integer 0-100>,
  "confidence": <integer 0-100>,
  "technology_stack": {{
    "identified_technologies": ["tech1", "tech2", ...],
    "primary_domain": "<main technology domain>",
    "cutting_edge_correlation": {{
      "<technology_name>": "<specific correlation to 2025 state-of-the-art>"
    }}
  }},
  "business_assessment": {{
    "primary_use_case": "<clear one-sentence description>",
    "target_industries": ["industry1", "industry2"],
    "market_opportunity": "<TAM/SAM assessment and growth potential>",
    "competitive_advantage": "<unique differentiator vs existing solutions>",
    "revenue_potential": "HIGH" | "MEDIUM" | "LOW"
  }},
  "innovation_factors": {{
    "novelty_score": <0-100>,
    "novelty_reasoning": "<why this is or isn't novel>",
    "feasibility_score": <0-100>,
    "feasibility_reasoning": "<technical feasibility assessment>",
    "scalability_score": <0-100>,
    "scalability_reasoning": "<scale potential>",
    "impact_score": <0-100>,
    "impact_reasoning": "<business and societal impact>"
  }},
  "trl_assessment": {{
    "level": <1-9>,
    "label": "<TRL label e.g. Basic Research / Proof of Concept / Prototype / Pilot / Production>",
    "description": "<current maturity description>"
  }},
  "strengths": ["strength1", "strength2", "strength3"],
  "concerns": ["concern1", "concern2"],
  "gaps_identified": ["gap1", "gap2"],
  "executive_summary": "<2-3 paragraph comprehensive summary of the technology and its innovation potential>",
  "recommendation": "<specific, actionable recommendation for innovation investment decision>",
  "comparable_innovations": ["<similar successful innovation 1>", "<similar innovation 2>"],
  "verdict_reasoning": "<clear explanation of why QUALIFIED or NOT_QUALIFIED>"
}}"""
    })

    return content

def analyze_with_claude(frames, transcript, pdf_text, duration):
    system_prompt = """You are a world-class Technology Innovation Analyst at a top-tier venture capital firm and innovation lab.

Your expertise spans:
- Identifying disruptive and cutting-edge technologies across all domains
- Correlating emerging tech with current 2024-2025 state-of-the-art research and deployments
- Assessing business viability, market timing, and ROI potential
- Technology Readiness Levels (TRL 1-9) assessment
- Innovation scoring based on novelty, feasibility, scalability, and impact

You analyze video presentations of technologies to determine:
1. Whether the technology is genuinely cutting-edge (aligned with or advancing 2025 frontiers)
2. Whether it has strong business use-case potential
3. Whether it qualifies for Innovation Program investment/support

Scoring criteria:
- QUALIFIED: Innovation score >= 65, strong business case, technically feasible
- NOT_QUALIFIED: Score < 65, incremental improvement only, poor business case, or not technically credible

You ALWAYS respond with pure, valid JSON only. No markdown, no explanation outside JSON."""

    content = build_analysis_prompt(frames, transcript, pdf_text, duration)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": content}]
    )

    response_text = response.content[0].text.strip()

    # Clean up common JSON wrapping
    if response_text.startswith("```json"):
        response_text = response_text[7:]
    if response_text.startswith("```"):
        response_text = response_text[3:]
    if response_text.endswith("```"):
        response_text = response_text[:-3]

    response_text = response_text.strip()

    # Extract JSON object
    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group())

    return json.loads(response_text)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/analyze', methods=['POST'])
def analyze():
    if 'video' not in request.files:
        return jsonify({'error': 'No video file provided'}), 400

    video_file = request.files['video']
    pdf_file = request.files.get('presentation')

    if not video_file.filename:
        return jsonify({'error': 'Empty video file'}), 400

    with tempfile.TemporaryDirectory() as tmpdir:
        # Save video
        video_ext = os.path.splitext(video_file.filename)[1].lower()
        video_path = os.path.join(tmpdir, f'video{video_ext}')
        video_file.save(video_path)

        # Save and process PDF
        pdf_text = ""
        if pdf_file and pdf_file.filename:
            pdf_ext = os.path.splitext(pdf_file.filename)[1].lower()
            pdf_path = os.path.join(tmpdir, f'presentation{pdf_ext}')
            pdf_file.save(pdf_path)
            pdf_text = extract_pdf_text(pdf_path)

        # Validate and extract frames
        try:
            frames, duration = extract_video_frames(video_path)
        except subprocess.TimeoutExpired:
            return jsonify({'error': 'Video processing timed out'}), 400
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            return jsonify({'error': f'Frame extraction failed: {str(e)}'}), 500

        if not frames:
            return jsonify({'error': 'Could not extract frames from video'}), 400

        # Extract transcript
        transcript = extract_audio_transcript(video_path)

        # Analyze with Claude
        try:
            analysis = analyze_with_claude(frames, transcript, pdf_text, duration)
        except json.JSONDecodeError as e:
            return jsonify({'error': f'Analysis parsing failed: {str(e)}'}), 500
        except anthropic.APIError as e:
            return jsonify({'error': f'AI analysis failed: {str(e)}'}), 500
        except Exception as e:
            return jsonify({'error': f'Analysis error: {str(e)}'}), 500

        return jsonify({
            'success': True,
            'meta': {
                'duration_seconds': round(duration, 1),
                'duration_formatted': f"{int(duration//60)}m {int(duration%60)}s",
                'frames_analyzed': len(frames),
                'has_transcript': bool(transcript and len(transcript.strip()) > 30),
                'has_presentation': bool(pdf_text and len(pdf_text.strip()) > 20),
            },
            'analysis': analysis
        })

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'model': 'claude-sonnet-4-6'})

if __name__ == '__main__':
    print("Video Innovation Analyzer starting on http://localhost:5000")
    app.run(debug=False, port=5000, host='0.0.0.0')
