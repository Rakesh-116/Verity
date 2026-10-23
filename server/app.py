"""MCP entry point: registers the project's primitive tools."""

from mcp.server.fastmcp import FastMCP

from tools.home_tools import (
    get_home_state,
    get_occupancy,
    list_devices,
    move_person,
    set_device_state,
)
from tools.context_tools import (
    get_active_speaker,
    get_last_session_summary,
    get_person_context,
    get_scene,
    remember_preference,
    remember_scene,
    set_active_speaker,
)
from tools.mobility_tools import (
    approve_ride_booking,
    book_ride,
    compare_ride_options,
    create_ride_booking_proposal,
)
from tools.delivery_tools import (
    approve_order,
    compare_item_prices,
    create_order_proposal,
    place_order,
)
from tools.approval_tools import list_pending_actions
from tools.hedge_tools import (
    approve_ride_hedge,
    cancel_ride_hedge,
    create_ride_hedge_proposal,
    get_ride_hedge_status,
    list_ride_hedges,
    start_ride_hedge,
)
from tools.routine_tools import get_routines
from tools.calendar_tools import find_meeting_deadline
from tools.household_tools import get_household, resolve_household_names, set_member_presence
from tools.proactive_tools import (
    approve_energy_saving_proposal,
    create_energy_saving_proposal,
    execute_energy_saving_proposal,
    get_energy_saving_opportunities,
)
from tools.robot_tools import get_robot_status, send_robot_to_room
from tools.travel_tools import compare_travel_options
from tools.college_tools import get_assessment_status

mcp = FastMCP("Verity")
for tool in (
    get_home_state,
    get_occupancy,
    list_devices,
    set_device_state,
    move_person,
    get_active_speaker,
    set_active_speaker,
    get_person_context,
    remember_preference,
    get_last_session_summary,
    remember_scene,
    get_scene,
    compare_ride_options,
    create_ride_booking_proposal,
    approve_ride_booking,
    book_ride,
    compare_item_prices,
    create_order_proposal,
    approve_order,
    place_order,
    list_pending_actions,
    get_energy_saving_opportunities,
    create_energy_saving_proposal,
    approve_energy_saving_proposal,
    execute_energy_saving_proposal,
    get_robot_status,
    send_robot_to_room,
    compare_travel_options,
    get_assessment_status,
    create_ride_hedge_proposal,
    approve_ride_hedge,
    start_ride_hedge,
    get_ride_hedge_status,
    list_ride_hedges,
    cancel_ride_hedge,
    get_routines,
    find_meeting_deadline,
    get_household,
    resolve_household_names,
    set_member_presence,
):
    mcp.tool()(tool)
