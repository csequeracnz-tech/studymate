# StudyMate

StudyMate is a self-hosted AI study workspace for learning from your own
documents, researching external sources, and creating useful academic
artifacts.

The built-in assistant is called **El Amigo**.

> Early community release. StudyMate is functional but still under active
> development and should currently be treated as experimental software.

## What it does

StudyMate combines local document processing and retrieval with an external
AI reasoning agent.

Current capabilities include:

- Subjects and study workspaces
- Multi-file study material
- PDF, DOCX, PPTX, XLSX, CSV, text, Markdown and image ingestion
- PDF page, PowerPoint slide and spreadsheet-sheet provenance
- OCR support through Tesseract
- Semantic search using Sentence Transformers
- Hybrid lexical + semantic retrieval
- Persistent study conversations
- Material-only question answering
- Material + external research mode
- Structured research-source cards
- Study summaries
- AI-assisted artifact planning
- DOCX generation
- PDF generation
- PowerPoint generation
- Excel workbook generation

## Architecture

The core pipeline is:

    documents
        ↓
    extraction
        ↓
    structured chunks + provenance
        ↓
    embeddings / search index
        ↓
    hybrid retrieval
        ↓
    relevant evidence
        ↓
    AI reasoning agent
        ↓
    grounded response or artifact
        ↓
    deterministic renderer

StudyMate deliberately avoids sending an entire document collection to the
AI model. Relevant evidence is retrieved first.

For generated artifacts the current pipeline is:

    user request
        ↓
    AI retrieval planner
        ↓
    multi-query hybrid retrieval
        ↓
    evidence assembly
        ↓
    artifact specialist
        ↓
    quality review
        ↓
    deterministic DOCX / PDF / PPTX / XLSX renderer

## AI backend

The current release uses a local OpenAI-compatible Hermes Agent endpoint.

By default StudyMate expects:

    http://127.0.0.1:8642/v1/chat/completions

The current implementation also expects Hermes configuration at:

    ~/.hermes/config.yaml

This integration will be made provider-configurable in a future release.

StudyMate itself does not contain or distribute AI API credentials.

## Requirements

- Python 3.12 recommended
- Tesseract OCR
- A running Hermes Agent OpenAI-compatible API
- Enough RAM for the embedding model

The current embedding model is:

    intfloat/e5-base-v2

It is downloaded by Sentence Transformers when first required.

## Installation

Clone the repository and create a virtual environment:

    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt

Install Tesseract using your operating system package manager.

For Debian/Ubuntu:

    sudo apt update
    sudo apt install tesseract-ocr

## Authentication

StudyMate currently uses a small local authentication configuration file:

    ~/.config/studymate/auth.env

Required values are documented in `.env.example`.

Passwords are not stored directly. StudyMate uses a salted scrypt password
hash.

The authentication setup will be simplified in a future community release.

## Run

From the repository root:

    source .venv/bin/activate
    uvicorn app.main:app --host 127.0.0.1 --port 8000

Then place StudyMate behind an HTTPS reverse proxy or another trusted private
access layer.

Do not expose the development server or the Hermes API directly to the public
Internet.

## Data

Runtime data is intentionally excluded from Git.

StudyMate may create data in:

- `database/`
- `data/documents/`
- `data/projects/`
- `index/`
- `logs/`
- `exports/`

Uploaded study material, extracted text, databases and generated artifacts
must not be committed.

## Security

The current application includes:

- Signed sessions
- Secure-cookie support
- CSRF protection
- Login rate limiting
- Local-only deployment support

This is an early release and has not undergone an independent security audit.

## Project status

StudyMate began as a personal experiment and is now being prepared as a
community project.

Some areas still need work:

- simpler first-run setup
- provider-independent AI configuration
- database migrations
- durable research-source persistence
- stronger scanned-document understanding
- richer visual understanding
- tests and CI
- packaging / container deployment
- documentation
- multi-user support

## Privacy

The repository does not include the original private study documents,
conversation database, generated artifacts, credentials, server configuration
or development backups used while prototyping StudyMate.

## Contributing

Issues, ideas and pull requests are welcome.

For significant changes, open an issue first so the implementation can be
discussed.

## License

MIT. See `LICENSE`.
