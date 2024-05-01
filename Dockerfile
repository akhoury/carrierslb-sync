FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    cron \
    supervisor 

RUN pip3 install playwright
RUN playwright install-deps 
RUN playwright install chromium

WORKDIR /app

COPY * ./

RUN pip3 install -r requirements.txt
CMD ["python3", "carrierslb_sync.py"]