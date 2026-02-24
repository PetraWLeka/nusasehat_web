# 🏗️ NusaHealth Cloud: Technical Architecture

This document provides a comprehensive technical overview of the NusaHealth Cloud platform, detailing the AI pipeline cascade, the forecasting implementation, and the underlying data flow.

## 1. The "Zero Data Leakage" AI Pipeline

Traditional EMR systems integrating AI often route sensitive patient health information to external 3rd-party APIs (like OpenAI or Anthropic). NusaHealth solves this severe privacy issue by leveraging Google's **open-weight MedGemma** models hosted privately on **Google Cloud Run**.

### Model Deployment Configuration
- **Compute**: Google Cloud Run with **L4 GPU** instances.
- **Serving Engine**: `vLLM` is used for high-throughput, low-latency concurrent inference.
- **Quantization**: 
  - The `MedGemma 4B IT` model runs in native FP16 for multimodal precision.
  - The `MedGemma 27B Text IT` model uses 4-bit quantization (AWQ/GPTQ) to fit into single L4 VRAM constraints while maintaining reasoning capability.
- **Scale-to-Zero**: Cloud Run automatically scales instances down to 0 when there are no active patient consultations or lab inspections, drastically reducing operational costs for under-funded Puskesmas.

### The AI Cascade (Triage -> Specialist)
To optimize speed and compute costs, NusaHealth employs a dual-model cascade:

1. **Frontline Triage (MedGemma 4B)**
   Every user message first hits the smaller, faster 4B model. Its job is to:
   - Identify immediate life-threatening conditions (Red Flag).
   - Answer simple queries (Green Flag).
   - Evaluate if the complexity requires a specialist.
2. **Specialist Escalation (MedGemma 27B)**
   If the 4B model outputs `needs_escalation=true`, or the confidence score is `< 0.6`, the system autonomously routes the conversation history and patient context to the 27B model for deep diagnostic reasoning.

## 2. Agentic Data Abstraction

During a consultation, MedGemma does not merely converse; it acts as an embedded data agent.

- **Automated Summarization**: At the end of a session, the 27B model summarizes the entire transcript into a structured `DiseaseReport`.
- **Entity Extraction**: It extracts `{illnesses: ["Diare"], items_needed: [{"item": "Oralit", "qty": 1}]}` utilizing JSON-mode prompting constraints.
- **Direct Database Linking**: These extracted JSON representations are immediately routed by Django into the `illness_tracking.csv` and `items_needed.csv` files, bypassing the need for doctors to manually double-enter diagnostic codes.

## 3. LightGBM Predictive Epidemiology

NusaHealth doesn't just record the past; it predicts the future.

### The Forecasting Engine
- **Framework**: Microsoft's `LightGBM`, chosen for its exceptional performance on tabular time-series data and robustness to missing entries.
- **Target**: Predicting daily case counts for top diseases (e.g., ISPA, Diare) and the corresponding supply depletion (e.g., Paracetamol, Zinc).
- **Horizon**: 14-day forward-looking forecast.

### Feature Engineering
The model fuses clinical data with environmental data:
1. **Lags & Rolling Statistics**: 1-day, 3-day, and 7-day rolling averages of historical disease instances from the CSV logs.
2. **Temporal Features**: Day of week, month, and seasonality indicators.
3. **Open-Meteo Integration**: We map the Puskesmas' GPS coordinates to Open-Meteo's historical and 14-day forecasted weather API. Features like `temperature_2m_mean`, `precipitation_sum`, and `relative_humidity_2m_mean` are heavily weighted by the model, as infectious diseases (like Dengue or ISPA) are strongly correlated with micro-climate shifts.

## 4. Security & Privacy

- **Data Locality**: SQLite/PostgreSQL databases remain strictly on the Puskesmas' physical or private cloud servers.
- **RAG (Retrieval-Augmented Generation)**: Utilizing **ChromaDB**, medical guidelines (PDFs) are chunked and vectorized locally. Context is injected into MedGemma's prompt securely, ensuring the AI strictly adheres to the Indonesian Ministry of Health's clinical pathways without hallucinating general web knowledge.
