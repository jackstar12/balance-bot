from fastapi import APIRouter

router = APIRouter(
    tags=["analytics"],
    dependencies=[],
    responses={
        401: {"msg": "Wrong Email or Password"},
        400: {"msg": "Email is already used"}
    }
)


