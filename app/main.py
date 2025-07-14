from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel
from kubernetes import client, config
import requests
import os
import json
from openai import AzureOpenAI

from k8s_utils import create_user_pod_and_service

app = FastAPI()

# OpenAI Client Configuration
openai_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)

# Request Models
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

class ManagerAgentRequest(BaseModel):
    user_id: str
    task: str

class SQLAgentRequest(BaseModel):
    user_id: str
    task: str
    context: str = ""

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

    res = requests.post(f"http://{ip}:5000/python", json={"code": req.code})
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

    try:
        res = requests.post(f"http://{ip}:5000/sql", json={"sql": req.sql})
        return res.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SQL request failed: {str(e)}")

@app.post("/manager-agent")
async def manager_agent(req: ManagerAgentRequest):
    try:
        # Manager Agent 负责任务拆分和协调
        system_prompt = """
        你是一个任务管理器，负责分析用户的任务并决定如何处理：
        1. 如果任务需要查询数据库，将其标记为 "sql_task"
        2. 如果任务只需要对话回复，将其标记为 "chat_task"
        3. 如果任务需要两者结合，将其拆分为多个子任务
        
        请用以下JSON格式回复：
        {
            "analysis": "任务分析",
            "tasks": [
                {
                    "type": "sql_task" 或 "chat_task",
                    "description": "子任务描述",
                    "priority": 1-5
                }
            ]
        }
        """
        
        response = openai_client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"用户任务: {req.task}"}
            ]
        )
        
        # 解析Manager Agent的回复
        manager_result = json.loads(response.choices[0].message.content)
        
        # 执行拆分后的任务
        task_results = []
        for task in manager_result["tasks"]:
            if task["type"] == "sql_task":
                # 调用SQL Agent
                sql_agent_req = SQLAgentRequest(
                    user_id=req.user_id,
                    task=task["description"],
                    context=req.task
                )
                result = await sql_agent(sql_agent_req)
                task_results.append({
                    "type": "sql_task",
                    "description": task["description"],
                    "result": result
                })
            elif task["type"] == "chat_task":
                # 直接对话处理
                chat_response = openai_client.chat.completions.create(
                    model=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
                    messages=[
                        {"role": "system", "content": "你是一个友好的助手，请根据用户的任务提供帮助。"},
                        {"role": "user", "content": task["description"]}
                    ]
                )
                task_results.append({
                    "type": "chat_task",
                    "description": task["description"],
                    "result": {"response": chat_response.choices[0].message.content}
                })
        
        # 生成最终回复
        final_prompt = f"""
        原始任务: {req.task}
        任务分析: {manager_result['analysis']}
        执行结果: {json.dumps(task_results, ensure_ascii=False)}
        
        请根据以上信息，生成一个完整且友好的回复给用户。
        """
        
        final_response = openai_client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
            messages=[
                {"role": "system", "content": "你是一个智能助手，请根据任务执行结果生成完整的回复。"},
                {"role": "user", "content": final_prompt}
            ]
        )
        
        return {
            "response": final_response.choices[0].message.content,
            "task_analysis": manager_result["analysis"],
            "sub_tasks": task_results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sql-agent")
async def sql_agent(req: SQLAgentRequest):
    try:
        # SQL Agent 负责生成和执行SQL代码
        system_prompt = """
        你是一个SQL专家，负责根据用户的任务生成SQL查询语句并执行。
        
        分析用户的任务，生成合适的SQL查询语句。
        如果需要更多信息（如表结构），请说明需要什么信息。
        
        请用以下JSON格式回复：
        {
            "analysis": "任务分析",
            "sql_query": "生成的SQL查询语句",
            "explanation": "SQL语句的解释"
        }
        """
        
        # 生成SQL查询
        response = openai_client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"任务: {req.task}\n上下文: {req.context}"}
            ]
        )
        
        sql_result = json.loads(response.choices[0].message.content)
        
        # 执行SQL查询
        if sql_result.get("sql_query"):
            try:
                sql_req = SQLRequest(user_id=req.user_id, sql=sql_result["sql_query"])
                execution_result = run_sql(sql_req)
                
                return {
                    "analysis": sql_result["analysis"],
                    "sql_query": sql_result["sql_query"],
                    "explanation": sql_result["explanation"],
                    "execution_result": execution_result
                }
            except Exception as e:
                return {
                    "analysis": sql_result["analysis"],
                    "sql_query": sql_result["sql_query"],
                    "explanation": sql_result["explanation"],
                    "execution_error": str(e)
                }
        else:
            return {
                "analysis": sql_result["analysis"],
                "message": "无法生成SQL查询，需要更多信息"
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
