FROM apache/superset:4.1.1
USER root
RUN pip install --no-cache-dir duckdb-engine==0.13.6 duckdb==1.5.6
COPY superset_config.py /app/pythonpath/superset_config.py
ENV SUPERSET_CONFIG_PATH=/app/pythonpath/superset_config.py
USER superset
