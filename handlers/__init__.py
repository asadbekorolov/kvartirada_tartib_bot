from handlers.start import router as start_router
from handlers.duty import router as duty_router
from handlers.cleaning import router as cleaning_router
from handlers.swap import router as swap_router
from handlers.expense import router as expense_router
from handlers.guest import router as guest_router
from handlers.fund import router as fund_router
from handlers.rules import router as rules_router

__all__ = [
    "start_router",
    "duty_router",
    "cleaning_router",
    "swap_router",
    "expense_router",
    "guest_router",
    "fund_router",
    "rules_router",
]
