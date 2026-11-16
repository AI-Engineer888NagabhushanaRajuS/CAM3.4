# Apache Superset configuration for the CAM 3.4 Reports & Analytics embed.
# The secret key comes from the environment (SUPERSET_SECRET_KEY); nothing secret is written here.
import os

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]
SQLALCHEMY_DATABASE_URI = "sqlite:////app/superset_home/superset.db"
# Embedded dashboards: a guest token minted by the CAM daemon lets the page show one dashboard, filtered to one RFQ.
FEATURE_FLAGS = {"EMBEDDED_SUPERSET": True}
GUEST_ROLE_NAME = "CAM_Guest"
GUEST_TOKEN_JWT_SECRET = os.environ["SUPERSET_SECRET_KEY"]
GUEST_TOKEN_JWT_AUDIENCE = "superset"
TALISMAN_ENABLED = False
WTF_CSRF_ENABLED = True
ENABLE_PROXY_FIX = True
