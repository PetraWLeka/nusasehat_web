#!/bin/bash
python3 -m vllm.entrypoints.openai.api_server \
    --host 0.0.0.0 \
    --port 8080 \
    --model ${MODEL_NAME} \
    --gpu-memory-utilization 0.95 \
    --max-model-len 4096 \
    --enforce-eager \
    ${EXTRA_VLLM_ARGS}