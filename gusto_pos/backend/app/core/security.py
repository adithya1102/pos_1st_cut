# from passlib.context import CryptContext

# pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__backend="builtin")

# def verify_password(plain_password: str, hashed_password: str) -> bool:
#     return pwd_context.verify(plain_password, hashed_password)

# def get_password_hash(password: str) -> str:
#     return pwd_context.hash(password)





from passlib.context import CryptContext
import hashlib

# 1. Clean context definition using standard schemes
pwd_context = CryptContext(schemes=["sha256_crypt", "md5_crypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    # If it's a legacy bcrypt hash from our database seed, intercept and check it
    if hashed_password.startswith("$2b$") or hashed_password.startswith("$2a$"):
        try:
            import bcrypt
            return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
        except Exception:
            # Safe local fallback verification logic if the engine fails
            return False
            
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)