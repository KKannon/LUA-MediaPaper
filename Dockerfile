FROM node:24-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY app/ ./app/
COPY mediapaper/ ./mediapaper/
COPY launcher.py ./
COPY static/wallpapers/ ./static/wallpapers/
COPY --from=frontend /build/static/frontend/ ./static/frontend/
RUN useradd --create-home lua
RUN mkdir -p /home/lua/data && chown lua:lua /home/lua/data
USER lua
EXPOSE 8765
CMD ["python", "launcher.py", "--server", "--host", "0.0.0.0", "--port", "8765"]
