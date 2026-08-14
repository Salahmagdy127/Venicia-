"""كل نماذج النظام — استيراد موحّد عشان Alembic يشوف الجداول كلها."""

from app.db.base import Base
from app.models.analytics import (
    DailyCategoryStatistics,
    DailyOutletStatistics,
    DailyStatistics,
    NightAuditRun,
)
from app.models.billing import DocumentSequence, Invoice, InvoiceLine
from app.models.channels import (
    Channel,
    ChannelBooking,
    ChannelMapping,
    ChannelMessage,
)
from app.models.maintenance import MaintenanceTicket, MinibarItem
from app.models.folio import Folio, FolioLine, Payment
from app.models.guests import Company, Guest, GuestDocument
from app.models.organization import Property
from app.models.pos import (
    KitchenStation,
    KotTicket,
    MenuCategory,
    MenuItem,
    Outlet,
    PosOrder,
    PosOrderLine,
    PosTable,
    Shift,
    menu_item_outlet,
)
from app.models.rates import (
    CancellationPolicy,
    RateCalendarEntry,
    RatePlan,
    RateRule,
    Season,
)
from app.models.reservations import (
    AvailabilityCalendar,
    Reservation,
    ReservationNight,
    ReservationUnit,
    WaitlistEntry,
)
from app.models.security import (
    AuditLog,
    LoginAttempt,
    Permission,
    Role,
    User,
    role_permission,
    user_role,
)
from app.models.units import Unit, UnitCategory, UnitStatusLog

__all__ = [
    "Base",
    # organization
    "Property",
    # security
    "User",
    "Role",
    "Permission",
    "AuditLog",
    "LoginAttempt",
    "user_role",
    "role_permission",
    # units
    "UnitCategory",
    "Unit",
    "UnitStatusLog",
    # rates
    "CancellationPolicy",
    "RatePlan",
    "Season",
    "RateRule",
    "RateCalendarEntry",
    # guests
    "Guest",
    "Company",
    "GuestDocument",
    # reservations
    "AvailabilityCalendar",
    "Reservation",
    "ReservationUnit",
    "ReservationNight",
    "WaitlistEntry",
    # folio
    "Folio",
    "FolioLine",
    "Payment",
    # pos
    "Outlet",
    "KitchenStation",
    "PosTable",
    "MenuCategory",
    "MenuItem",
    "Shift",
    "PosOrder",
    "PosOrderLine",
    "KotTicket",
    "menu_item_outlet",
    # billing
    "Invoice",
    "InvoiceLine",
    "DocumentSequence",
    # channels
    "Channel",
    "ChannelMapping",
    "ChannelMessage",
    "ChannelBooking",
    # maintenance
    "MaintenanceTicket",
    "MinibarItem",
    # analytics
    "DailyStatistics",
    "DailyCategoryStatistics",
    "DailyOutletStatistics",
    "NightAuditRun",
]
