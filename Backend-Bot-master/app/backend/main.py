from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import ResponseValidationError

from app.backend.middlewares.exception import setup_error_middleware
from app.backend.openapi_schema import custom_openapi
from app.backend.middlewares import DBSessionMiddleware
from app.backend.routers import user_router
from app.backend.routers.ride import ride_router
from app.backend.routers.role import role_router
from app.backend.routers.driver_profile import driver_profile_router
from app.backend.routers.driver_document import driver_document_router
from app.backend.routers.phone_verification import phone_verification_router
from app.backend.routers.commission import commission_router
from app.backend.routers.driver_location import driver_location_router
from app.backend.routers.chat_message import chat_message_router
from app.backend.routers.transaction import transaction_router
# Optional debug router is disabled for smoke run

app = FastAPI()
app.openapi = lambda: custom_openapi(app)
app.add_middleware(DBSessionMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
setup_error_middleware(app)

app.include_router(user_router, tags=['User'])
app.include_router(ride_router, tags=['Ride'])
app.include_router(role_router, tags=['Role'])
app.include_router(driver_profile_router, tags=['DriverProfile'])
app.include_router(driver_document_router, tags=['DriverDocument'])
app.include_router(phone_verification_router, tags=['PhoneVerification'])
app.include_router(commission_router, tags=['Commission'])
app.include_router(driver_location_router, tags=['DriverLocation'])
app.include_router(chat_message_router, tags=['ChatMessage'])
app.include_router(transaction_router, tags=['Transaction'])
# app.include_router(pg_errs_router, tags=["Debug"])


@app.exception_handler(ResponseValidationError)
async def validation_exception_handler(request: Request, exc: ResponseValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Validation error occurred",
            # "errors": exc.errors(),
            "body": exc.body,
        },
    )


@app.get("/")
async def hello_world():
    return {"message": "Hello, World!"}
