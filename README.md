# 🏥 NusaHealth Cloud

![NusaHealth Banner](https://img.shields.io/badge/MedGemma-Powered_Health_Center_Management-10b981?style=for-the-badge)
![Cloud Run](https://img.shields.io/badge/Deployed_on-Google_Cloud_Run_L4_GPU-4285F4?style=for-the-badge&logo=googlecloud)
![Django](https://img.shields.io/badge/Django-5.2-092E20?style=for-the-badge&logo=django)
![TailwindCSS](https://img.shields.io/badge/Tailwind-CSS-38B2AC?style=for-the-badge&logo=tailwind-css)

**NusaHealth Cloud** is a next-generation, AI-native Health Center (Puskesmas) Management System designed specifically for the **Med-Gemma Impact Challenge**. It leverages Google's state-of-the-art open-weight models (**MedGemma 4B** and **MedGemma 27B**) running entirely on your own infrastructure via **Google Cloud Run (Free L4 GPU)**.

Watch full demo below
https://github.com/user-attachments/assets/8fa6d780-3ac1-4f5b-bec4-e02bf78609a6


With NusaHealth Cloud, **no patient data ever leaves your server**.

---

## ✨ Why NusaHealth Cloud?

Traditional Electronic Medical Records (EMRs) are passive data silos. NusaHealth transforms the EMR into a **proactive AI assistant**:

1. **Zero Data Leakage (Privacy First)**
   Instead of sending sensitive patient data to external 3rd-party APIs, NusaHealth routes all AI tasks to your privately hosted MedGemma models on Cloud Run.
2. **AI-Powered Diagnostics & Multimodal Analysis**
   Upload X-rays, CT scans, dermatology photos, or histology slides. The system uses **MedGemma 1.5 4B IT** to analyze images and return findings with anatomical localization.
3. **Automated Clinical Data Extraction**
   During AI consultations, MedGemma automatically extracts structured data (diagnoses, required medications, and supplies).
4. **Predictive Epidemiology (LightGBM)**
   NusaHealth doesn't just record the past; it predicts the future. By combining historical consultation data with **Open-Meteo weather forecasts**, our integrated LightGBM time-series models predict disease trends and supply needs up to 14 days in advance.
5. **Holistic Stunting Prevention**
   A dedicated module providing AI-generated nutritional guidance, local crop recommendations, and educational materials based on Indonesian Ministry of Health guidelines.

---

## 🧠 Dual-Model AI Architecture

NusaHealth intelligently routes tasks between two distinct MedGemma models depending on the required reasoning depth and modality:

| Model | Parameters | Type | Primary Role | Infrastructure |
|---|---|---|---|---|
| **MedGemma 1.5 4B IT** | 4 Billion | Multimodal (Vision + Text) | Medical image analysis (7+ types), OCR on lab reports, fast frontline triage, data extraction. | **Cloud Run (L4 GPU)** |
| **MedGemma 27B Text IT** | 27 Billion | Text Only (4-bit QTZ) | Deep diagnostic reasoning, complex treatment planning, and specialist-level case abstraction. | **Cloud Run (L4 GPU)** |

*Both models are configured via `vLLM` on Cloud Run utilizing the `Scale-to-Zero` principle, ensuring you only pay for exact compute milliseconds used.*

---

## 🚀 Quick Start / Local Setup

Follow these steps to deploy NusaHealth Cloud locally for development and testing.

### 1. Prerequisites
- Python 3.10+
- Redis Server (Native or via WSL on Windows)
- Google Cloud Project with Cloud Run deployed MedGemma endpoints

### 2. Installation
```bash
git clone <repo-url>
cd nusasehat_web
python -m venv python_venv 
# Activate venv:
# Windows: python_venv\Scripts\activate
# Mac/Linux: source python_venv/bin/activate

pip install -r requirements.txt
```

### 3. Environment Configuration (`.env`)
Create a `.env` file in the root directory:
```env
DJANGO_SECRET_KEY=your-super-secret-key
DJANGO_DEBUG=True
GCP_PROJECT_ID=your-gcp-project-id
GOOGLE_APPLICATION_CREDENTIALS=credentials.json
CLOUD_RUN_4B_URL=https://medgemma-4b-xxxxx.a.run.app
CLOUD_RUN_27B_URL=https://medgemma-27b-xxxxx.a.run.app
CELERY_BROKER_URL=redis://localhost:6379/0
```

### 4. Database Setup & Seeding
```bash
python manage.py migrate
python manage.py create_default_admin
python manage.py seed_crops

# Start the Django development server
python manage.py runserver
```

### 5. Start Background Workers
NusaHealth relies on Celery to process asynchronous AI inference without blocking the UI.
In a separate terminal (with the virtual environment activated):
```bash
# On Windows:
celery -A nusahealth_cloud worker -l info --pool=solo

# On Mac/Linux:
celery -A nusahealth_cloud worker -l info
```

🎉 **Access the dashboard at `http://localhost:8000`** (Login: `admin` / Password: `admin123`)

---

## 🏗️ Project Structure & Modules

The system is highly modularized into Django apps handling specific health center functions:

| Module | Description |
|---|---|
| `core/` | Authentication, beautiful glassmorphism Dashboard, Audit Logging, and Village Profile Settings. |
| `patients/` | Comprehensive EMR, Patient Registration, and WHO Z-Score Stunting Detection. |
| `consultations/` | AI Consultation UI. Supports text/image inputs, clinical guideline RAG, and escalation. |
| `laboratory/` | Dedicated medical imaging suite (X-Ray, standard photos, lab results) powered by multimodal MedGemma. |
| `reports/` | Real-time epidemiology dashboard. Features LightGBM forecast visualizations and automated CSV logging. |
| `library/` | Upload clinical PDFs. Automatically chunks, embeds, and indexes into local ChromaDB for RAG context. |
| `nutrition/` | Village-specific agricultural recommendations and AI nutrition chat. |
| `education/` | Generates shareable, printable infographics and disease prevention materials for the public. |

---

## 🏆 Kaggle Med-Gemma Impact Challenge: Agentic Workflow Prize

NusaHealth Cloud is structurally designed to be a premier candidate for the **Agentic Workflow Prize**. 
The prize is awarded for projects that most effectively reimagine complex workflows by deploying HAI-DEF models as intelligent agents. 

**How NusaHealth Reimagines the Workflow:**
Before NusaHealth, health center data collection, image analysis, and resource planning were isolated manual processes prone to error and disconnected from patient outcomes. We overhauled this challenging process by deploying MedGemma natively within the workflow:
1. **Agentic Consultations (`MedGemma 27B`)**: Instead of doctors manually filling out EMR forms, the AI acts as an asynchronous agent observing the chat. It autonomously abstracts clinical notes, diagnoses, and exact supplies needed entirely from natural conversation.
2. **Vision-Driven Workflow (`MedGemma 4B`)**: Medical images (X-rays, Lab Reports) are passed to the 4B multimodal agent, which automatically parses them for anatomical regions and localized findings, removing the transcription bottleneck for lab technicians.
3. **Downstream Autonomy (LightGBM)**: The structured outputs from these AI agents are continuously piped directly into LightGBM predictive models. The AI agent doesn't just 'generate text'; it powers fully autonomous predictive epidemiology without human data-entry interference.

By chaining MedGemma 4B (fast vision/triage) securely to MedGemma 27B (complex specialist abstraction), we created a true **Agentic Workflow** that measurably improves clinical efficiency, resource allocation capability, and ultimate patient outcomes.

---

## 📚 Documentation

For deep technical dives and tutorials, please refer to our consolidated documentation:

| Document | Description |
|---|---|
| [architecture_and_tech.md](architecture_and_tech.md) | Full technical architecture reference, AI pipeline cascade, and data flow. |


---

<p align="center">
  <i>Built to secure the health of Indonesia's communities with open-weight AI.</i>
</p>
