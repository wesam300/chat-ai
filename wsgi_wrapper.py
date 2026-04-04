from a2wsgi import ASGIMiddleware
from web_app import app

# هذا الملف هو الجسر الذي يسمح لـ PythonAnywhere بتشغيل FastAPI
# في إعدادات "Web" في PythonAnywhere، يجب أن يكون المسار يشير إلى 'application'
application = ASGIMiddleware(app)
