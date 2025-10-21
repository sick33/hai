FROM python:3.11-slim
WORKDIR /app

# (권장) 의존성 먼저 설치
# requirements.txt가 있다면:
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 최소 패키지 직접 설치(requirements.txt가 없다면)
RUN pip install --no-cache-dir flask gunicorn pandas

# 앱 복사
COPY hai_adapter.py ./hai_adapter.py
COPY data ./data   

EXPOSE 8000
CMD ["gunicorn","-w","4","-b","0.0.0.0:8000","hai_adapter:app"]