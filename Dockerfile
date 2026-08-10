FROM python:3.11-slim

# Ishchi papka
WORKDIR /app

# Dependencylarni o'rnatish
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Loyiha fayllarini ko'chirish
COPY . .

# Botni ishga tushirish
CMD ["python", "bot.py"]
