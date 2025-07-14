from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel
import subprocess
import os
import shutil
from pathlib import Path
import pyodbc
from fastapi import HTTPException

app = FastAPI()

# 创建数据存储目录
DATA_DIR = Path("/data")
DATA_DIR.mkdir(exist_ok=True)

class CodeRequest(BaseModel):
    code: str

class ShellRequest(BaseModel):
    command: str

class SQLRequest(BaseModel):
    sql: str


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        # 保存文件到数据目录
        file_path = DATA_DIR / file.filename
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"message": f"File {file.filename} uploaded successfully"}
    except Exception as e:
        return {"error": str(e)}
    
@app.post("/python")
def run_code(req: CodeRequest):
    try:
        # 设置工作目录为数据目录
        os.chdir(DATA_DIR)
        output = subprocess.check_output(["python3", "-c", req.code], stderr=subprocess.STDOUT, timeout=5)
        return {"output": output.decode()}
    except subprocess.CalledProcessError as e:
        return {"error": e.output.decode()}
    except Exception as e:
        return {"error": str(e)}

@app.post("/shell")
def run_shell(req: ShellRequest):
    try:
        # 可选：也在 /data 目录下执行
        os.chdir(DATA_DIR)
        # 直接在 shell 中执行命令
        output = subprocess.check_output(
            req.command,
            shell=True,
            stderr=subprocess.STDOUT,
            timeout=10
        )
        return {"output": output.decode()}
    except subprocess.CalledProcessError as e:
        return {"error": e.output.decode()}
    except Exception as e:
        return {"error": str(e)}
    
def get_sql_connection():
    server = os.getenv("AZURE_SQL_SERVER")
    database = os.getenv("AZURE_SQL_DATABASE")
    username = os.getenv("AZURE_SQL_USERNAME")
    password = os.getenv("AZURE_SQL_PASSWORD")
    driver = os.getenv("AZURE_SQL_DRIVER", "{ODBC Driver 17 for SQL Server}")

    conn_str = f"DRIVER={driver};SERVER={server};DATABASE={database};UID={username};PWD={password}"
    return pyodbc.connect(conn_str)

@app.post("/sql")
def run_sql(req: SQLRequest):
    try:
        conn = get_sql_connection()
        cursor = conn.cursor()
        cursor.execute(req.sql)

        if req.sql.strip().lower().startswith("select"):
            columns = [column[0] for column in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            result = {"type": "select", "rows": rows}
        else:
            conn.commit()
            result = {"type": "command", "message": f"{cursor.rowcount} rows affected"}

        cursor.close()
        conn.close()
        return result

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))