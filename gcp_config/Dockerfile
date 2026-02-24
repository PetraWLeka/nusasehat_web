FROM vllm/vllm-openai:latest

ENV HF_HOME=/model-cache

ARG MODEL_NAME
ENV MODEL_NAME=$MODEL_NAME

# 1. Copy the token and download the model while the internet is ON
COPY hf_token.txt /hf_token.txt
RUN HF_TOKEN=$(cat /hf_token.txt) && \
    python3 -c "from huggingface_hub import snapshot_download; snapshot_download('${MODEL_NAME}', token='${HF_TOKEN}')" && \
    rm /hf_token.txt

# 2. NOW turn off the internet connection so it boots fast later
ENV HF_HUB_OFFLINE=1

# 3. Start the server
COPY start.sh /start.sh
RUN chmod +x /start.sh
ENTRYPOINT ["/start.sh"]