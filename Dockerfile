FROM python:3.11-slim

# Hugging Face Spaces run as user 1000
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .
USER user

ENV ORT_THREADS=2 MODEL_DIR=model
EXPOSE 7860
# Render sets $PORT; Hugging Face uses 7860
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-7860} --workers 1
