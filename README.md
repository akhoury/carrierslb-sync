You need to first install 

```
pip install playwright
playwright install-deps 
playwright install chromium

pip3 install -r requirements.txt

cp config.cfg.example config.cfg
# edit config.cfg

python3 carrierslb_sync.py

```

or just use docker

```
docker build -t carrierslb_sync:latest .
docker run -it carrierslb_sync:latest
```

