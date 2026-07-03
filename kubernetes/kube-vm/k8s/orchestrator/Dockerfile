FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py perception_agent.py state_agent.py \
     planning_agent.py execution_agent.py orchestrator.py ./

CMD ["python3", "-u", "orchestrator.py"]
