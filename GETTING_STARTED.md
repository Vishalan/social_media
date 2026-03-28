# Getting Started — Step by Step

## Phase 0: Environment Setup (30 min)

### 1. Python Environment
```bash
cd /Users/vishalan/Documents/Projects/social_media
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. API Keys
```bash
cp .env.example .env
# Edit .env and add your keys:
# - ANTHROPIC_API_KEY (get from console.anthropic.com)
# - ELEVENLABS_API_KEY (get from elevenlabs.io/app/settings/api-keys)
# - AYRSHARE_API_KEY (get from app.ayrshare.com — $15/mo plan for multi-platform)
# - YOUTUBE_API_KEY (get from console.cloud.google.com — YouTube Data API v3)
# - RUNPOD_API_KEY (get from runpod.io/console/user/settings)
```

### 3. Verify Setup
```bash
python -c "from dotenv import load_dotenv; load_dotenv(); import os; print('Anthropic:', 'SET' if os.getenv('ANTHROPIC_API_KEY') else 'MISSING')"
```

## Phase 1: Finalize Niche (1 hour)

### Run the Niche Analysis Notebook
```bash
jupyter notebook notebooks/01_niche_analysis.ipynb
```
This runs a weighted scoring model across 15 niches on 6 dimensions. It produces:
- Composite ranking bar chart
- RPM revenue comparison
- Monthly revenue projections at 500K views
- Radar chart comparing top 5 niches
- (Optional) Live Google Trends data

After reviewing results, update `config/settings.py`:
```python
BRAND = {
    "name": "YourChosenBrandName",
    "niche": "AI & Technology",  # or whatever scored highest
    ...
}
```

## Phase 2: Brand & Accounts (2-3 hours)

### 1. Choose Brand Name
Requirements:
- Available as handle on YouTube, TikTok, Instagram, X, Facebook, LinkedIn, Pinterest
- Available as .com domain (optional but recommended)
- Niche-relevant, memorable, no personal name (keeps it faceless/sellable)

Check availability: namecheckr.com or namechk.com

### 2. Create Accounts (all on the same day)
- [ ] Google Brand Account (for YouTube — not personal account)
- [ ] YouTube channel
- [ ] TikTok Business account
- [ ] Instagram Creator account
- [ ] Facebook Page
- [ ] X (Twitter) account
- [ ] LinkedIn Page
- [ ] Pinterest Business account
- [ ] Linktree or Beacons page
- [ ] Brand email (brandname@gmail.com)

### 3. Design Branding in Canva
- Logo (square, works at small sizes)
- YouTube banner (2560x1440)
- Channel art for all platforms
- 3-5 thumbnail templates
- Color palette (2-3 brand colors)

Save all assets to `assets/` folder.

## Phase 3: Voice Setup (30 min)

### ElevenLabs Voice Selection
```bash
# List available voices
cd scripts/
python -c "
from voiceover.voice_generator import VoiceGenerator
vg = VoiceGenerator()
voices = vg.list_voices()
for v in voices:
    print(f'{v[\"voice_id\"]}: {v[\"name\"]}')
"
```

Pick a voice (or clone your own on elevenlabs.io) and update `config/settings.py`:
```python
VOICE = {
    "voice_id": "your_chosen_voice_id",
    ...
}
```

## Phase 4: GPU Cloud Setup (1 hour)

### Option A: Vast.ai (cheapest — ~$0.44/hr for RTX 4090)
```bash
# Run cost comparison first
python deploy/gpu_cost_comparison.py

# Then provision
bash deploy/vastai/setup.sh
```

### Option B: RunPod (more reliable — ~$0.69/hr)
```bash
bash deploy/runpod/setup_comfyui.sh
```

### Option C: Local Docker (if you have a GPU)
```bash
cd deploy/
docker-compose up -d
```

After ComfyUI is running, update `scripts/config.example.json` (or pass `--comfyui-url` to the CLI):
```json
{
  "comfyui_url": "http://your-gpu-server:8188"
}
```

## Phase 5: YouTube OAuth Setup (30 min)

1. Go to console.cloud.google.com
2. Create a project (or use existing)
3. Enable "YouTube Data API v3"
4. Create OAuth 2.0 credentials (Desktop app)
5. Download `client_secret.json` to `config/client_secret.json`
6. First run will open browser for OAuth consent

## Phase 6: Test the Pipeline (1 hour)

### Test each module individually:
```bash
cd scripts/

# 1. Generate a test script
python -c "
from content_gen.script_generator import ScriptGenerator
sg = ScriptGenerator(api_provider='anthropic', niche='AI & Technology')
result = sg.generate_short_form('5 AI Tools Nobody Talks About')
print(result)
"

# 2. Generate a test voiceover
python -c "
from voiceover.voice_generator import VoiceGenerator
vg = VoiceGenerator()
vg.generate('This is a test of the voiceover system.', '../output/audio/test.mp3')
"

# 3. Test ComfyUI connection
python -c "
from video_gen.comfyui_client import ComfyUIClient
client = ComfyUIClient('http://localhost:8188')
print('ComfyUI status:', client.get_status('test'))
"

# 4. Run full single-video pipeline
python pipeline.py single --topic "5 AI Tools Nobody Talks About" --type short
```

### Test cross-platform posting (start with a test post):
```bash
python pipeline.py single --topic "Testing our new AI channel" --type short --post
```

## Phase 7: Go Live (ongoing)

### Daily workflow:
```bash
# Automated daily content production
python scripts/pipeline.py daily

# Or batch a full week on Sunday
python scripts/pipeline.py weekly
```

### Set up cron for automation:
```bash
# Run daily at 8 AM
crontab -e
# Add: 0 8 * * * cd /Users/vishalan/Documents/Projects/social_media && .venv/bin/python scripts/pipeline.py daily >> automation.log 2>&1
```

### Or use n8n:
1. Install n8n: `npm install -g n8n` or use Docker
2. Import `n8n_flows/content_pipeline.json`
3. Configure API credentials in n8n UI
4. Enable the workflow

## Monitoring & Optimization

### Weekly analytics:
```bash
python scripts/pipeline.py report --period week
```

### Export data for deeper analysis:
```bash
python -c "
from analytics.tracker import AnalyticsTracker
tracker = AnalyticsTracker()
tracker.export_csv('../output/analytics_export.csv')
"
```
