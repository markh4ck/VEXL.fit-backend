from fastapi import FastAPI, APIRouter, HTTPException, Depends, UploadFile, File, Header, Query, Request
from fastapi.responses import Response
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional, Dict, Any
import uuid
import secrets
import bcrypt
from datetime import datetime, timezone
import requests
# Object Storage
import cloudinary
import cloudinary.uploader


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')
cloudinary.config(
    secure=True  # usa automáticamente CLOUDINARY_URL del .env
)

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Stripe
import stripe

# Initialize Stripe with platform key
PLATFORM_STRIPE_KEY = os.environ.get("STRIPE_API_KEY")
stripe.api_key = PLATFORM_STRIPE_KEY



def upload_file_to_cloudinary(file_bytes: bytes, folder: str):
    result = cloudinary.uploader.upload(
        file_bytes,
        folder=folder
    )
    return result["secure_url"]




app = FastAPI()
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== MODELS ==========

# Influencer Models
class InfluencerCreate(BaseModel):
    name: str
    brand_name: str
    email: EmailStr

class InfluencerUpdate(BaseModel):
    name: Optional[str] = None
    brand_name: Optional[str] = None
    logo_url: Optional[str] = None
    custom_color: Optional[str] = "#CDF22B"
    stripe_account_id: Optional[str] = None
    stripe_api_key: Optional[str] = None  # Opción manual
    subscription_price: Optional[float] = 29.99
    platform_fee_percent: Optional[float] = 5.0  # Comisión de la plataforma

class InfluencerResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    brand_name: str
    email: str
    logo_url: Optional[str] = None
    custom_color: str = "#CDF22B"
    access_code: str
    user_access_code: str
    stripe_account_id: Optional[str] = None
    stripe_connected: bool = False  # True si tiene Stripe Connect
    stripe_manual: bool = False  # True si tiene API key manual
    subscription_price: float = 29.99
    platform_fee_percent: float = 5.0
    subscription_status: str = "active"
    created_at: str
    total_users: int = 0

# User Models
class UserRegister(BaseModel):
    email: EmailStr
    password: str
    name: str
    access_code: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str
    brand_name: str

class UserResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    email: str
    name: str
    influencer_id: str
    brand_name: str
    created_at: str
    subscription_status: str = "pending"

class UserProgressCreate(BaseModel):
    weight: Optional[float] = None
    body_fat: Optional[float] = None
    notes: Optional[str] = None

class UserProgressResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    weight: Optional[float] = None
    body_fat: Optional[float] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None
    created_at: str

# Workout Models
class ExerciseCreate(BaseModel):
    name: str
    video_url: Optional[str] = None
    sets: int = 3
    reps: int = 10
    rest_time: int = 60
    description: Optional[str] = None

class ExerciseResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    video_url: Optional[str] = None
    sets: int
    reps: int
    rest_time: int
    description: Optional[str] = None

class WorkoutCreate(BaseModel):
    name: str
    description: Optional[str] = None
    category: str = "General"
    duration_minutes: int = 45
    difficulty: str = "Intermediate"
    exercises: List[ExerciseCreate] = []

class WorkoutResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    influencer_id: str
    name: str
    description: Optional[str] = None
    category: str
    duration_minutes: int
    difficulty: str
    exercises: List[ExerciseResponse] = []
    created_at: str

# Nutrition Models
class NutritionPlanCreate(BaseModel):
    user_id: str
    name: str
    calories: int
    protein: int
    carbs: int
    fats: int
    meals: List[Dict[str, Any]] = []
    notes: Optional[str] = None

class NutritionPlanResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    influencer_id: str
    name: str
    calories: int
    protein: int
    carbs: int
    fats: int
    meals: List[Dict[str, Any]]
    notes: Optional[str] = None
    created_at: str

# ========== SUPER ADMIN ENDPOINTS ==========

SUPER_ADMIN_CODE = "VEXL-SUPERADMIN-2024"

def verify_super_admin(admin_code: str = Header(None, alias="X-Admin-Code")):
    if admin_code != SUPER_ADMIN_CODE:
        raise HTTPException(status_code=403, detail="Invalid admin code")
    return True

@api_router.post("/admin/influencers", response_model=InfluencerResponse)
async def create_influencer(data: InfluencerCreate, _: bool = Depends(verify_super_admin)):
    # Check if brand_name already exists
    existing = await db.influencers.find_one({"brand_name": data.brand_name.lower().replace(" ", "-")}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=400, detail="Brand name already exists")
    
    influencer = {
        "id": str(uuid.uuid4()),
        "name": data.name,
        "brand_name": data.brand_name.lower().replace(" ", "-"),
        "email": data.email,
        "logo_url": None,
        "custom_color": "#CDF22B",
        "access_code": secrets.token_urlsafe(16),
        "user_access_code": secrets.token_urlsafe(8),
        "stripe_account_id": None,
        "subscription_price": 29.99,
        "subscription_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_users": 0
    }
    await db.influencers.insert_one(influencer)
    del influencer["_id"]
    return influencer

@api_router.get("/admin/influencers", response_model=List[InfluencerResponse])
async def list_influencers(_: bool = Depends(verify_super_admin)):
    influencers = await db.influencers.find({}, {"_id": 0}).to_list(1000)
    for inf in influencers:
        user_count = await db.users.count_documents({"influencer_id": inf["id"]})
        inf["total_users"] = user_count
    return influencers

@api_router.patch("/admin/influencers/{influencer_id}/status")
async def toggle_influencer_status(influencer_id: str, _: bool = Depends(verify_super_admin)):
    influencer = await db.influencers.find_one({"id": influencer_id}, {"_id": 0})
    if not influencer:
        raise HTTPException(status_code=404, detail="Influencer not found")
    
    new_status = "suspended" if influencer["subscription_status"] == "active" else "active"
    await db.influencers.update_one({"id": influencer_id}, {"$set": {"subscription_status": new_status}})
    return {"status": new_status}

@api_router.get("/admin/metrics")
async def get_admin_metrics(_: bool = Depends(verify_super_admin)):
    total_influencers = await db.influencers.count_documents({})
    active_influencers = await db.influencers.count_documents({"subscription_status": "active"})
    total_users = await db.users.count_documents({})
    paid_users = await db.users.count_documents({"subscription_status": "paid"})
    
    # Calculate MRR
    influencers = await db.influencers.find({"subscription_status": "active"}, {"_id": 0, "id": 1, "subscription_price": 1}).to_list(1000)
    mrr = 0.0
    for inf in influencers:
        user_count = await db.users.count_documents({"influencer_id": inf["id"], "subscription_status": "paid"})
        mrr += user_count * inf.get("subscription_price", 29.99)
    
    return {
        "total_influencers": total_influencers,
        "active_influencers": active_influencers,
        "total_users": total_users,
        "paid_users": paid_users,
        "mrr": round(mrr, 2)
    }

# ========== INFLUENCER ENDPOINTS ==========

async def get_influencer_by_code(access_code: str = Header(None, alias="X-Access-Code")):
    if not access_code:
        raise HTTPException(status_code=401, detail="Access code required")
    influencer = await db.influencers.find_one({"access_code": access_code}, {"_id": 0})
    if not influencer:
        raise HTTPException(status_code=403, detail="Invalid access code")
    if influencer["subscription_status"] != "active":
        raise HTTPException(status_code=403, detail="Account suspended")
    return influencer

@api_router.get("/influencer/profile", response_model=InfluencerResponse)
async def get_influencer_profile(influencer: dict = Depends(get_influencer_by_code)):
    user_count = await db.users.count_documents({"influencer_id": influencer["id"]})
    influencer["total_users"] = user_count
    return influencer

@api_router.patch("/influencer/profile", response_model=InfluencerResponse)
async def update_influencer_profile(data: InfluencerUpdate, influencer: dict = Depends(get_influencer_by_code)):
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if update_data:
        await db.influencers.update_one({"id": influencer["id"]}, {"$set": update_data})
    updated = await db.influencers.find_one({"id": influencer["id"]}, {"_id": 0})
    user_count = await db.users.count_documents({"influencer_id": updated["id"]})
    updated["total_users"] = user_count
    return updated

@api_router.post("/influencer/upload-logo")
async def upload_logo(file: UploadFile = File(...), influencer: dict = Depends(get_influencer_by_code)):
    data = await file.read()
    
    # Subir a Cloudinary
    result = cloudinary.uploader.upload(
        data,
        folder=f"vexlfit/logos/{influencer['id']}"
    )
    
    url = result["secure_url"]
    
    # Guardar en DB
    await db.influencers.update_one(
        {"id": influencer["id"]},
        {"$set": {"logo_url": url}}
    )
    
    return {"url": url}

# ========== STRIPE CONNECT ENDPOINTS ==========

class StripeConnectRequest(BaseModel):
    return_url: str
    refresh_url: str

@api_router.post("/influencer/stripe/connect")
async def create_stripe_connect_account(data: StripeConnectRequest, influencer: dict = Depends(get_influencer_by_code)):
    """Crea una cuenta Express de Stripe Connect y devuelve el link de onboarding"""
    try:
        # Verificar si ya tiene cuenta
        if influencer.get("stripe_account_id"):
            # Crear nuevo link de onboarding para cuenta existente
            account_link = stripe.AccountLink.create(
                account=influencer["stripe_account_id"],
                type="account_onboarding",
                refresh_url=data.refresh_url,
                return_url=data.return_url
            )
            return {"url": account_link.url, "account_id": influencer["stripe_account_id"]}
        
        # Crear nueva cuenta Express
        account = stripe.Account.create(
            type="express",
            country="US",
            email=influencer["email"],
            capabilities={
                "card_payments": {"requested": True},
                "transfers": {"requested": True}
            },
            business_type="individual",
            metadata={
                "influencer_id": influencer["id"],
                "brand_name": influencer["brand_name"]
            }
        )
        
        # Guardar account_id
        await db.influencers.update_one(
            {"id": influencer["id"]},
            {"$set": {"stripe_account_id": account.id, "stripe_connected": False}}
        )
        
        # Crear link de onboarding
        account_link = stripe.AccountLink.create(
            account=account.id,
            type="account_onboarding",
            refresh_url=data.refresh_url,
            return_url=data.return_url
        )
        
        return {"url": account_link.url, "account_id": account.id}
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe Connect error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@api_router.get("/influencer/stripe/status")
async def get_stripe_connect_status(influencer: dict = Depends(get_influencer_by_code)):
    """Verifica el estado de la cuenta Stripe Connect"""
    stripe_account_id = influencer.get("stripe_account_id")
    stripe_api_key = influencer.get("stripe_api_key")
    
    result = {
        "has_stripe_connect": False,
        "stripe_connect_complete": False,
        "has_manual_key": bool(stripe_api_key),
        "can_receive_payments": False,
        "account_id": stripe_account_id
    }
    
    if stripe_account_id:
        try:
            account = stripe.Account.retrieve(stripe_account_id)
            result["has_stripe_connect"] = True
            result["stripe_connect_complete"] = account.details_submitted
            result["charges_enabled"] = account.charges_enabled
            result["payouts_enabled"] = account.payouts_enabled
            result["can_receive_payments"] = account.charges_enabled
            
            # Actualizar estado en DB
            await db.influencers.update_one(
                {"id": influencer["id"]},
                {"$set": {"stripe_connected": account.details_submitted}}
            )
        except stripe.error.StripeError as e:
            logger.error(f"Stripe status error: {e}")
    
    if stripe_api_key:
        result["can_receive_payments"] = True
    
    return result

@api_router.post("/influencer/stripe/manual-key")
async def set_manual_stripe_key(influencer: dict = Depends(get_influencer_by_code), stripe_key: str = ""):
    """Guarda la API key de Stripe manual del influencer"""
    if not stripe_key or not stripe_key.startswith("sk_"):
        raise HTTPException(status_code=400, detail="Invalid Stripe API key format")
    
    # Verificar que la key funciona
    try:
        test_stripe = stripe.api_key
        stripe.api_key = stripe_key
        stripe.Balance.retrieve()
        stripe.api_key = test_stripe
    except stripe.error.AuthenticationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe API key")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error validating key: {str(e)}")
    
    # Guardar key (en producción deberías encriptarla)
    await db.influencers.update_one(
        {"id": influencer["id"]},
        {"$set": {"stripe_api_key": stripe_key, "stripe_manual": True}}
    )
    
    return {"success": True, "message": "Stripe API key saved successfully"}

@api_router.delete("/influencer/stripe/manual-key")
async def remove_manual_stripe_key(influencer: dict = Depends(get_influencer_by_code)):
    """Elimina la API key manual"""
    await db.influencers.update_one(
        {"id": influencer["id"]},
        {"$unset": {"stripe_api_key": ""}, "$set": {"stripe_manual": False}}
    )
    return {"success": True}

# Workouts
@api_router.post("/influencer/workouts", response_model=WorkoutResponse)
async def create_workout(data: WorkoutCreate, influencer: dict = Depends(get_influencer_by_code)):
    exercises = []
    for ex in data.exercises:
        exercises.append({
            "id": str(uuid.uuid4()),
            **ex.model_dump()
        })
    
    workout = {
        "id": str(uuid.uuid4()),
        "influencer_id": influencer["id"],
        "name": data.name,
        "description": data.description,
        "category": data.category,
        "duration_minutes": data.duration_minutes,
        "difficulty": data.difficulty,
        "exercises": exercises,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.workouts.insert_one(workout)
    del workout["_id"]
    return workout

@api_router.get("/influencer/workouts", response_model=List[WorkoutResponse])
async def list_influencer_workouts(influencer: dict = Depends(get_influencer_by_code)):
    workouts = await db.workouts.find({"influencer_id": influencer["id"]}, {"_id": 0}).to_list(1000)
    return workouts

@api_router.get("/influencer/workouts/{workout_id}", response_model=WorkoutResponse)
async def get_workout(workout_id: str, influencer: dict = Depends(get_influencer_by_code)):
    workout = await db.workouts.find_one({"id": workout_id, "influencer_id": influencer["id"]}, {"_id": 0})
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")
    return workout

@api_router.put("/influencer/workouts/{workout_id}", response_model=WorkoutResponse)
async def update_workout(workout_id: str, data: WorkoutCreate, influencer: dict = Depends(get_influencer_by_code)):
    exercises = []
    for ex in data.exercises:
        exercises.append({
            "id": str(uuid.uuid4()),
            **ex.model_dump()
        })
    
    update_data = {
        "name": data.name,
        "description": data.description,
        "category": data.category,
        "duration_minutes": data.duration_minutes,
        "difficulty": data.difficulty,
        "exercises": exercises
    }
    
    result = await db.workouts.update_one(
        {"id": workout_id, "influencer_id": influencer["id"]},
        {"$set": update_data}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Workout not found")
    
    workout = await db.workouts.find_one({"id": workout_id}, {"_id": 0})
    return workout

@api_router.delete("/influencer/workouts/{workout_id}")
async def delete_workout(workout_id: str, influencer: dict = Depends(get_influencer_by_code)):
    result = await db.workouts.delete_one({"id": workout_id, "influencer_id": influencer["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Workout not found")
    return {"deleted": True}

# CRM - Users management
@api_router.get("/influencer/users", response_model=List[UserResponse])
async def list_influencer_users(influencer: dict = Depends(get_influencer_by_code)):
    users = await db.users.find({"influencer_id": influencer["id"]}, {"_id": 0, "password_hash": 0}).to_list(1000)
    return users

@api_router.get("/influencer/users/{user_id}")
async def get_user_detail(user_id: str, influencer: dict = Depends(get_influencer_by_code)):
    user = await db.users.find_one({"id": user_id, "influencer_id": influencer["id"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    progress = await db.user_progress.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).to_list(100)
    nutrition = await db.nutrition_plans.find_one({"user_id": user_id}, {"_id": 0})
    
    return {
        "user": user,
        "progress": progress,
        "nutrition_plan": nutrition
    }

# Nutrition Plans
@api_router.post("/influencer/nutrition", response_model=NutritionPlanResponse)
async def create_nutrition_plan(data: NutritionPlanCreate, influencer: dict = Depends(get_influencer_by_code)):
    # Verify user belongs to influencer
    user = await db.users.find_one({"id": data.user_id, "influencer_id": influencer["id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Upsert nutrition plan
    plan = {
        "id": str(uuid.uuid4()),
        "user_id": data.user_id,
        "influencer_id": influencer["id"],
        "name": data.name,
        "calories": data.calories,
        "protein": data.protein,
        "carbs": data.carbs,
        "fats": data.fats,
        "meals": data.meals,
        "notes": data.notes,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.nutrition_plans.update_one(
        {"user_id": data.user_id},
        {"$set": plan},
        upsert=True
    )
    return plan

@api_router.get("/influencer/analytics")
async def get_influencer_analytics(influencer: dict = Depends(get_influencer_by_code)):
    total_users = await db.users.count_documents({"influencer_id": influencer["id"]})
    paid_users = await db.users.count_documents({"influencer_id": influencer["id"], "subscription_status": "paid"})
    total_workouts = await db.workouts.count_documents({"influencer_id": influencer["id"]})
    
    revenue = paid_users * influencer.get("subscription_price", 29.99)
    
    # Get recent users
    recent_users = await db.users.find(
        {"influencer_id": influencer["id"]},
        {"_id": 0, "password_hash": 0}
    ).sort("created_at", -1).limit(5).to_list(5)
    
    return {
        "total_users": total_users,
        "paid_users": paid_users,
        "pending_users": total_users - paid_users,
        "total_workouts": total_workouts,
        "monthly_revenue": round(revenue, 2),
        "recent_users": recent_users
    }

# ========== USER/STUDENT ENDPOINTS ==========

@api_router.get("/brand/{brand_name}")
async def get_brand_info(brand_name: str):
    influencer = await db.influencers.find_one(
        {"brand_name": brand_name.lower()},
        {"_id": 0, "access_code": 0}
    )
    if not influencer:
        raise HTTPException(status_code=404, detail="Brand not found")
    if influencer["subscription_status"] != "active":
        raise HTTPException(status_code=403, detail="This brand is currently unavailable")
    
    return {
        "id": influencer["id"],
        "name": influencer["name"],
        "brand_name": influencer["brand_name"],
        "logo_url": influencer.get("logo_url"),
        "custom_color": influencer.get("custom_color", "#CDF22B"),
        "subscription_price": influencer.get("subscription_price", 29.99)
    }

@api_router.post("/user/register", response_model=UserResponse)
async def register_user(data: UserRegister):
    # Find influencer by user_access_code
    influencer = await db.influencers.find_one({"user_access_code": data.access_code}, {"_id": 0})
    if not influencer:
        raise HTTPException(status_code=400, detail="Invalid access code")
    if influencer["subscription_status"] != "active":
        raise HTTPException(status_code=403, detail="This brand is currently unavailable")
    
    # Check if email exists for this influencer
    existing = await db.users.find_one({"email": data.email, "influencer_id": influencer["id"]}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    password_hash = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    
    user = {
        "id": str(uuid.uuid4()),
        "email": data.email,
        "name": data.name,
        "password_hash": password_hash,
        "influencer_id": influencer["id"],
        "brand_name": influencer["brand_name"],
        "subscription_status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user)
    
    response = {k: v for k, v in user.items() if k not in ["_id", "password_hash"]}
    return response

@api_router.post("/user/login")
async def login_user(data: UserLogin):
    influencer = await db.influencers.find_one({"brand_name": data.brand_name.lower()}, {"_id": 0})
    if not influencer:
        raise HTTPException(status_code=400, detail="Brand not found")
    
    user = await db.users.find_one({"email": data.email, "influencer_id": influencer["id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")
    
    if not bcrypt.checkpw(data.password.encode(), user["password_hash"].encode()):
        raise HTTPException(status_code=400, detail="Invalid credentials")
    
    # Simple token (user_id)
    return {
        "token": user["id"],
        "user": {k: v for k, v in user.items() if k != "password_hash"},
        "brand": {
            "name": influencer["name"],
            "brand_name": influencer["brand_name"],
            "logo_url": influencer.get("logo_url"),
            "custom_color": influencer.get("custom_color", "#00FF41")
        }
    }

async def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization required")
    user_id = authorization.replace("Bearer ", "")
    user = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user

@api_router.get("/user/profile")
async def get_user_profile(user: dict = Depends(get_current_user)):
    influencer = await db.influencers.find_one({"id": user["influencer_id"]}, {"_id": 0, "access_code": 0})
    return {
        "user": user,
        "brand": {
            "name": influencer["name"],
            "brand_name": influencer["brand_name"],
            "logo_url": influencer.get("logo_url"),
            "custom_color": influencer.get("custom_color", "#00FF41")
        }
    }

@api_router.get("/user/workouts", response_model=List[WorkoutResponse])
async def get_user_workouts(user: dict = Depends(get_current_user)):
    workouts = await db.workouts.find({"influencer_id": user["influencer_id"]}, {"_id": 0}).to_list(1000)
    return workouts

@api_router.get("/user/workouts/{workout_id}", response_model=WorkoutResponse)
async def get_user_workout(workout_id: str, user: dict = Depends(get_current_user)):
    workout = await db.workouts.find_one({"id": workout_id, "influencer_id": user["influencer_id"]}, {"_id": 0})
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")
    return workout

@api_router.post("/user/progress", response_model=UserProgressResponse)
async def add_progress(data: UserProgressCreate, user: dict = Depends(get_current_user)):
    progress = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "weight": data.weight,
        "body_fat": data.body_fat,
        "photo_url": None,
        "notes": data.notes,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.user_progress.insert_one(progress)
    del progress["_id"]
    return progress

@api_router.post("/user/progress/photo")
async def upload_progress_photo(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    data = await file.read()

    # Subir a Cloudinary
    result = cloudinary.uploader.upload(
        data,
        folder=f"vexlfit/progress/{user['id']}",
        transformation=[
            {"width": 800, "height": 800, "crop": "limit"},
            {"quality": "auto"}
        ]
    )

    url = result["secure_url"]

    # Guardar progreso
    progress = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "weight": None,
        "body_fat": None,
        "photo_url": url,
        "notes": "Progress photo",
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    await db.user_progress.insert_one(progress)

    return {"url": url, "progress_id": progress["id"]}

@api_router.get("/user/progress", response_model=List[UserProgressResponse])
async def get_user_progress(user: dict = Depends(get_current_user)):
    progress = await db.user_progress.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return progress

@api_router.get("/user/nutrition")
async def get_user_nutrition(user: dict = Depends(get_current_user)):
    plan = await db.nutrition_plans.find_one({"user_id": user["id"]}, {"_id": 0})
    return plan

# ========== FILE SERVING ==========

# ========== STRIPE PAYMENT ==========

class CheckoutRequest(BaseModel):
    origin_url: str

@api_router.post("/checkout/create")
async def create_checkout(data: CheckoutRequest, user: dict = Depends(get_current_user)):
    influencer = await db.influencers.find_one(
        {"id": user["influencer_id"]},
        {"_id": 0}
    )
    if not influencer:
        raise HTTPException(status_code=404, detail="Brand not found")

    # ✅ Validar URL
    if not data.origin_url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid origin URL")

    host_url = data.origin_url.rstrip("/")
    success_url = f"{host_url}/{influencer['brand_name']}/payment-success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{host_url}/{influencer['brand_name']}"

    # ✅ Evitar errores de float
    amount = float(influencer.get("subscription_price", 29.99))
    unit_amount = int(round(amount * 100))

    platform_fee_percent = float(influencer.get("platform_fee_percent", 5.0))

    stripe_account_id = influencer.get("stripe_account_id")
    stripe_connected = influencer.get("stripe_connected", False)

    payment_method = "platform"

    try:
        # ==============================
        # 🔥 OPCIÓN 1: STRIPE CONNECT
        # ==============================
        if stripe_account_id and stripe_connected:
            payment_method = "connect"

            application_fee = int(round(unit_amount * (platform_fee_percent / 100)))

            session = stripe.checkout.Session.create(
                mode="payment",
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": unit_amount,
                        "product_data": {
                            "name": f"Suscripción {influencer['name']}",
                            "description": f"Acceso mensual a {influencer['brand_name']}"
                        }
                    },
                    "quantity": 1
                }],
                payment_intent_data={
                    "application_fee_amount": application_fee,
                    "transfer_data": {
                        "destination": stripe_account_id
                    }
                },
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "user_id": user["id"],
                    "email": user.get("email"),
                    "influencer_id": influencer["id"],
                    "brand_name": influencer["brand_name"],
                    "payment_method": "connect"
                }
            )

        # ==============================
        # 🔥 OPCIÓN 2: PLATAFORMA (CLEAN)
        # ==============================
        else:
            payment_method = "platform"

            session = stripe.checkout.Session.create(
                mode="payment",
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": unit_amount,
                        "product_data": {
                            "name": f"Suscripción {influencer['name']}",
                            "description": f"Acceso mensual a {influencer['brand_name']}"
                        }
                    },
                    "quantity": 1
                }],
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "user_id": user["id"],
                    "email": user.get("email"),
                    "influencer_id": influencer["id"],
                    "brand_name": influencer["brand_name"],
                    "payment_method": "platform"
                }
            )

        # ==============================
        # 💾 GUARDAR TRANSACCIÓN
        # ==============================
        transaction = {
            "id": str(uuid.uuid4()),
            "session_id": session.id,
            "user_id": user["id"],
            "influencer_id": influencer["id"],
            "stripe_account_id": stripe_account_id,
            "amount": amount,
            "currency": "usd",
            "payment_method": payment_method,
            "platform_fee": amount * (platform_fee_percent / 100) if payment_method == "connect" else 0,
            "payment_status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        await db.payment_transactions.insert_one(transaction)

        return {
            "url": session.url,
            "session_id": session.id,
            "payment_method": payment_method
        }

    except stripe.error.StripeError as e:
        logger.error(f"Stripe checkout error: {e}")
        raise HTTPException(status_code=400, detail=f"Payment error: {str(e)}")
    
@api_router.get("/checkout/status/{session_id}")
async def get_checkout_status(session_id: str, request: Request):
    # Buscar la transacción para saber qué método se usó
    transaction = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
    
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    payment_method = transaction.get("payment_method", "platform")
    influencer = await db.influencers.find_one({"id": transaction["influencer_id"]}, {"_id": 0})
    
    try:
        if payment_method == "manual" and influencer and influencer.get("stripe_api_key"):
            # Usar la key del influencer
            original_key = stripe.api_key
            stripe.api_key = influencer["stripe_api_key"]
            try:
                session = stripe.checkout.Session.retrieve(session_id)
                payment_status = "paid" if session.payment_status == "paid" else session.payment_status
            finally:
                stripe.api_key = original_key
        else:
            # Usar key de la plataforma (Connect o Platform)
            session = stripe.checkout.Session.retrieve(session_id)
            payment_status = "paid" if session.payment_status == "paid" else session.payment_status
        
        # Actualizar si está pagado
        if payment_status == "paid" and transaction["payment_status"] != "paid":
            await db.payment_transactions.update_one(
                {"session_id": session_id},
                {"$set": {"payment_status": "paid"}}
            )
            await db.users.update_one(
                {"id": transaction["user_id"]},
                {"$set": {"subscription_status": "paid"}}
            )
        
        return {
            "status": session.status,
            "payment_status": payment_status,
            "amount_total": session.amount_total,
            "currency": session.currency
        }
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe status error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@api_router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature")

    endpoint_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            endpoint_secret
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=400, detail="Webhook error")

    # ==============================
    # 🎯 EVENTOS IMPORTANTES
    # ==============================
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        session_id = session.get("id")
        metadata = session.get("metadata", {})

        # ✅ Marcar transacción como pagada
        await db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {
                "payment_status": "paid",
                "updated_at": datetime.now(timezone.utc).isoformat()
            }}
        )

        # ✅ Activar suscripción usuario
        user_id = metadata.get("user_id")
        if user_id:
            await db.users.update_one(
                {"id": user_id},
                {"$set": {
                    "subscription_status": "paid",
                    "subscription_updated_at": datetime.now(timezone.utc).isoformat()
                }}
            )

    # (Opcional pero PRO)
    elif event["type"] == "checkout.session.expired":
        session = event["data"]["object"]

        await db.payment_transactions.update_one(
            {"session_id": session.get("id")},
            {"$set": {"payment_status": "expired"}}
        )

    return {"received": True}

# ========== ROOT ENDPOINT ==========

@api_router.get("/")
async def root():
    return {"message": "VEXL.fit API", "version": "1.0.0"}

# Include router and middleware
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
