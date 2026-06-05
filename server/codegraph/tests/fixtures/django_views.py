"""Django function-based views fixture.

Covers: @api_view decorator with various HTTP methods.
"""
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status


@api_view(["GET"])
def user_list(request):
    """List all users."""
    users = ["alice", "bob"]
    return Response({"users": users})


@api_view(["GET", "POST"])
def user_detail(request, user_id: int):
    """Get or update a user."""
    if request.method == "GET":
        return Response({"id": user_id, "name": "alice"})
    elif request.method == "POST":
        return Response({"status": "updated"}, status=status.HTTP_200_OK)


@api_view(["DELETE"])
def user_delete(request, user_id: int):
    """Delete a user."""
    return Response(status=status.HTTP_204_NO_CONTENT)
