FROM python:3.12-slim

WORKDIR /app

# Las dependencias primero: asi la imagen se cachea aunque cambie el codigo.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
