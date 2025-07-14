from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel
from k8s_utils import create_user_pod_and_service
from kubernetes import client, config
import requests
from openai import AzureOpenAI
import os
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fastapi import HTTPException
import re

app = FastAPI()

openai_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)

class UserRequest(BaseModel):
    user_id: str

class PythonRequest(BaseModel):
    user_id: str
    code: str

class ShellRequest(BaseModel):
    user_id: str
    command: str

class GPTRequest(BaseModel):
    user_id: str
    instruction: str

class SQLRequest(BaseModel):
    user_id: str
    sql: str

class SQLConfigRequest(BaseModel):
    user_id: str
    sql_server: str
    sql_database: str
    sql_username: str
    sql_password: str
    sql_driver: str = "{ODBC Driver 17 for SQL Server}"


@app.post("/create")
def create_user_environment(req: UserRequest):
    pod_name = f"userpod-{req.user_id}"
    svc_name = f"usersvc-{req.user_id}"
    try:
        create_user_pod_and_service(pod_name, svc_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create environment: {str(e)}")

    return {
        "message": "User environment created",
        "pod": pod_name,
        "service": svc_name
    }

@app.post("/create-with-sql")
def create_with_sql(req: SQLConfigRequest):
    pod_name = f"userpod-{req.user_id}"
    svc_name = f"usersvc-{req.user_id}"
    try:
        env_vars = [
            {"name": "AZURE_SQL_SERVER", "value": req.sql_server},
            {"name": "AZURE_SQL_DATABASE", "value": req.sql_database},
            {"name": "AZURE_SQL_USERNAME", "value": req.sql_username},
            {"name": "AZURE_SQL_PASSWORD", "value": req.sql_password},
            {"name": "AZURE_SQL_DRIVER", "value": req.sql_driver}
        ]
        create_user_pod_and_service(pod_name, svc_name, env_vars)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create environment with SQL config: {str(e)}")

    return {
        "message": "User environment with SQL config created",
        "pod": pod_name,
        "service": svc_name
    }

@app.post("/python")
def execute(req: PythonRequest):
    svc_name = f"usersvc-{req.user_id}"
    config.load_incluster_config()
    k8s = client.CoreV1Api()
    svc = k8s.read_namespaced_service(svc_name, namespace="default")

    ip = svc.spec.cluster_ip
    if not ip:
        raise HTTPException(status_code=404, detail="Pod not found")

    res = requests.post(f"http://{ip}:5000/execute", json={"code": req.code})
    return res.json()

@app.post("/shell")
def shell(req: ShellRequest):
    svc_name = f"usersvc-{req.user_id}"
    config.load_incluster_config()
    k8s = client.CoreV1Api()
    svc = k8s.read_namespaced_service(svc_name, namespace="default")

    ip = svc.spec.cluster_ip
    if not ip:
        raise HTTPException(status_code=404, detail="Pod not found")

    res = requests.post(f"http://{ip}:5000/shell", json={"command": req.command})
    return res.json()

@app.post("/upload/{user_id}")
async def upload_file(user_id: str, file: UploadFile = File(...)):
    svc_name = f"usersvc-{user_id}"
    config.load_incluster_config()
    k8s = client.CoreV1Api()
    svc = k8s.read_namespaced_service(svc_name, namespace="default")

    ip = svc.spec.cluster_ip
    if not ip:
        raise HTTPException(status_code=404, detail="Pod not found")

    files = {"file": (file.filename, file.file, file.content_type)}
    res = requests.post(f"http://{ip}:5000/upload", files=files)
    return res.json()

@app.post("/gpt")
async def gpt(req: GPTRequest):
    try:
        response = openai_client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
            messages=[
                {"role": "system", "content": "Hi."},
                {"role": "user", "content": req.instruction}
            ]
        )
        res = response.choices[0].message.content.strip()
        return {"response": res}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sql")
def run_sql(req: SQLRequest):
    svc_name = f"usersvc-{req.user_id}"
    config.load_incluster_config()
    k8s = client.CoreV1Api()
    svc = k8s.read_namespaced_service(svc_name, namespace="default")

    ip = svc.spec.cluster_ip
    if not ip:
        raise HTTPException(status_code=404, detail="Pod not found")

    # return {"message": "主服务 /sql 被调用了", "user_id": req.user_id, "sql": req.sql}
    try:
        res = requests.post(f"http://{ip}:5000/sql", json={"sql": req.sql})
        return res.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SQL request failed: {str(e)}")
