# shen-api

一个 FastAPI 小服务：输入 QQ 号 + 名字，生成“请问你看到xxx了吗”图片（PNG）。

# 声明

此项目由ChatGPT辅助构建！！！

## 1. 准备
确保目录结构类似：

- `app.py`
- `requirements.txt`
- `assets/`（里面放模板图 template.* 和字体 font.ttf）

## 2. 安装依赖
（建议在项目目录下执行）

```bash
pip install -r requirements.txt
```

可选：emoji 更稳（推荐）

```bash
pip install pilmoji
```

3. 启动服务

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

4. 测试接口
健康检查（bushi

```bash
curl http://127.0.0.1:8000/health
```

生成图片：
```bash
curl "http://127.0.0.1:8000/meme?qq=12345678&name=test%20%F0%9F%90%94" --output shen.png
```

浏览器也可以直接打开：
（示例
http://47.105.107.105:8000/meme?qq=3033597696&name=傻逼
![示例](http://47.105.107.105:8000/meme?qq=3033597696&name=%E5%82%BB%E9%80%BC)
