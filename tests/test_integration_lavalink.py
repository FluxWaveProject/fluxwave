import os
import socket

import pytest

import fluxwave


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lavalink_rest_smoke_from_environment() -> None:
    host = os.getenv("LAVALINK_HOST")
    port = os.getenv("LAVALINK_PORT")
    password = os.getenv("LAVALINK_PASSWORD")
    secure = os.getenv("LAVALINK_SECURE", "false").lower() == "true"

    if not host or not port or not password:
        pytest.skip("LAVALINK_HOST, LAVALINK_PORT, and LAVALINK_PASSWORD are required.")

    scheme = "https" if secure else "http"
    try:
        connect_host = host if secure else socket.gethostbyname(host)
    except socket.gaierror as exc:
        pytest.skip(f"Could not resolve Lavalink host from this environment: {exc}")
    client = fluxwave.RestClient(
        f"{scheme}://{connect_host}:{port}",
        password=password,
        user_id=0,
        client_name="FluxWave/Test",
        request_timeout=5,
        retries=0,
    )

    try:
        version = await client.fetch_version()
        info = await client.fetch_info()
        stats = await client.fetch_stats()
    finally:
        await client.close()

    assert version
    assert info.version.major >= 4
    assert stats.players >= 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lavalink_node_connect_and_resume_from_environment() -> None:
    host = os.getenv("LAVALINK_HOST")
    port = os.getenv("LAVALINK_PORT")
    password = os.getenv("LAVALINK_PASSWORD")
    secure = os.getenv("LAVALINK_SECURE", "false").lower() == "true"

    if not host or not port or not password:
        pytest.skip("LAVALINK_HOST, LAVALINK_PORT, and LAVALINK_PASSWORD are required.")

    scheme = "https" if secure else "http"
    try:
        connect_host = host if secure else socket.gethostbyname(host)
    except socket.gaierror as exc:
        pytest.skip(f"Could not resolve Lavalink host from this environment: {exc}")

    node = fluxwave.Node(
        f"{scheme}://{connect_host}:{port}",
        password=password,
        user_id=1,
        client_name="FluxWave/Integration",
        connect_timeout=5,
        request_timeout=5,
        retries=0,
        resume_timeout=30,
    )

    try:
        await node.connect()
        assert node.status is fluxwave.NodeStatus.CONNECTED
        assert node.session_id is not None
    finally:
        await node.close()
