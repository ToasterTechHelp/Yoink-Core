# Yoink! — Lecture Notes Component Extractor

Extract diagrams, tables, formulas, and text blocks from lecture notes (PDF or images) using AI-powered document layout detection.

## Project Structure

```
Yoink!/
├── backend/        # FastAPI extraction engine + API (Python)
│   ├── yoink/
│   │   ├── api/    # FastAPI routes, auth, storage, worker
│   │   └── ...     # Converter, detector, pipeline
│   └── tests/
├── frontend/       # Next.js 15 web app
│   └── src/
│       ├── app/    # Pages & routes
│       ├── components/
│       ├── lib/    # API client, Supabase helpers
│       └── store/  # Zustand state
└── supabase/       # Schema & RLS policies
```

## Architecture

- **Frontend** — Next.js 15, Tailwind CSS, shadcn/ui, Zustand
- **Backend** — FastAPI, async SQLite job queue, DocLayout-YOLO
- **Database** — Supabase (Postgres + Auth + Storage) for authenticated users; SQLite for guest job tracking
- **Auth** — Supabase Auth (Google OAuth), JWT verification via JWKS (ES256)

Guest users get ephemeral local processing. Authenticated users get persistent storage with up to 5 saved jobs.

## Getting Started

### Docker (recommended)

```bash
cp backend/.env.example backend/.env  # configure secrets
docker compose up --build
```

The API runs at `http://localhost:8000`. The YOLO model is downloaded during the Docker build.

### Backend (local dev)

```bash
cd backend
curl -LsSf https://astral.sh/uv/install.sh | sh  # install uv
uv sync                                            # install deps
cp .env.example .env                               # configure secrets
uv run uvicorn yoink.api.app:app --reload
```

The API runs at `http://localhost:8000`. Docs at `/docs`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local   # configure Supabase keys + API URL
npm run dev
```

The app runs at `http://localhost:3000`.

### API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/extract` | Upload a file (max 100MB), starts extraction job |
| GET | `/api/v1/jobs/{job_id}` | Get job status and progress |
| GET | `/api/v1/jobs/{job_id}/result` | Get result metadata |
| GET | `/api/v1/jobs/{job_id}/result/components?offset=0&limit=10` | Get a batch of components |
| DELETE | `/api/v1/jobs/{job_id}` | Cancel and clean up a job |
| POST | `/api/v1/feedback` | Submit a bug report or content violation |
| GET | `/api/v1/health` | Health check |

### Environment Variables

**Backend** (`backend/.env`):

| Variable | Description |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key (server-side only) |
| `SUPABASE_JWT_SECRET` | JWT secret for HS256 fallback |
| `YOINK_API_URL` | Public URL of this API |
| `YOINK_CORS_ORIGINS` | Comma-separated allowed origins |

**Frontend** (`frontend/.env.local`):

| Variable | Description |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon/public key |
| `NEXT_PUBLIC_API_URL` | Backend API URL |

## CLI Usage

```bash
cd backend

uv run python -m yoink lecture.pdf           # extract from PDF
uv run python -m yoink slide.png             # extract from image
uv run python -m yoink lecture.pdf -o ./out  # custom output dir
uv run python -m yoink lecture.pdf --conf 0.3
uv run python -m yoink lecture.pdf -v        # verbose
```

| Flag | Default | Description |
|---|---|---|
| `input_file` | *(required)* | Path to PDF or image file |
| `-o, --output-dir` | `./output` | Output directory for JSON |
| `--model-path` | *(auto-download)* | Path to YOLO `.pt` weights |
| `--imgsz` | `1024` | YOLO prediction image size |
| `--conf` | `0.2` | Confidence threshold (0–1) |
| `--device` | *(auto)* | `cpu` or `cuda:0` |
| `--dpi` | `200` | PDF rendering resolution |
| `-v, --verbose` | off | Verbose logging |

## Categories

| Category | Includes | YOLO Labels |
|---|---|---|
| **text** | Main text content and formulas | title, plain text, isolate_formula |
| **figure** | Visual elements | figure, table |
| **misc** | Captions, footnotes, headers/footers | abandon, figure_caption, table_caption, table_footnote, formula_caption |

## Supported File Types

- **PDF** (.pdf)
- **Images** (.png, .jpg, .jpeg, .bmp, .tiff, .webp)
- **PowerPoint** — coming soon

## Running Tests

```bash
cd backend
uv run pytest tests/ -v
```

## Roadmap

Future features:
- [IP] Add support for PowerPoint and Word
- [ ] Add toggle for bg remover
- [IP] Add ability to upload multiple images

Known issues:
- [ ] Allows too many file types to be uploaded
- [ ] Report button doesn't work