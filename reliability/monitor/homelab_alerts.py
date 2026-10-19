#!/usr/bin/env python3
"""Avisa no Telegram quando Immich, Bitwarden, Ceph ou o homelab mudam de estado.

A ponte é o Gestão no cloudvero, em 127.0.0.1:8101. O script não lê token da
Meta. O primeiro estado saudável só é gravado; o aviso sai na mudança, e também
na primeira leitura se o serviço já estiver ruim.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

BOT = os.environ.get("GESTAOBOT_URL", "http://127.0.0.1:8101").rstrip("/")
STATE = Path(os.environ.get(
    "HOMELAB_ALERT_STATE", "/opt/egkcluster/state/homelab-alerts.json"))
SSH_PORT = os.environ.get("EGK_NODE_SSH_PORT", "2222")
# minipcamd4 guarda OSD, mas a porta 2222 usada pelo cloudvero não responde.
CEPH_NODES = (
    "minipcamd.velociraptor-scylla.ts.net",
    "minipcamd2.velociraptor-scylla.ts.net",
    "minipcamd3.velociraptor-scylla.ts.net",
)
CONTAINERS = (
    ("immich_server", "immich"),
    ("immich_postgres", "immich"),
    ("immich_redis", "immich"),
    ("vaultwarden", "bitwarden"),
    ("homeassistant", "homelab"),
    ("tsdproxy", "homelab"),
    ("watchtower", "homelab"),
)


def docker_states() -> dict[str, str]:
    completed = subprocess.run(
        ["sudo", "-n", "docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"],
        capture_output=True, text=True, timeout=20, check=False)
    found = {}
    if completed.returncode != 0:
        return {name: "docker-indisponivel" for name, _area in CONTAINERS}
    for line in completed.stdout.splitlines():
        name, _, status = line.partition("\t")
        if name:
            found[name] = status.strip() or "sem-status"
    states = {}
    for name, _area in CONTAINERS:
        states[name] = _classe_container(found.get(name, "ausente"))
    for name, status in found.items():
        if name.startswith("ceph-"):
            states[name] = _classe_container(status)
    return states


def _classe_container(status: str) -> str:
    low = status.lower()
    if low == "ausente":
        return "ausente"
    if low.startswith("up") and "unhealthy" not in low:
        return "ok"
    if low.startswith("up"):
        return "unhealthy"
    return "down"


def ceph_units() -> dict[str, str]:
    states = {}
    remote = 'systemctl list-units "ceph*" --type=service --all --no-legend --plain --no-pager'
    for node in CEPH_NODES:
        completed = subprocess.run(
            ["ssh", "-p", SSH_PORT, "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
             f"root@{node}"],
            input=remote + "\n", capture_output=True, text=True, timeout=20, check=False)
        curto = node.split(".", 1)[0]
        if completed.returncode != 0:
            states[f"{curto}:ssh"] = "ssh-falhou"
            continue
        for line in completed.stdout.splitlines():
            parts = line.split()
            if len(parts) < 4 or "ceph" not in parts[0]:
                continue
            unit, active, sub = parts[0], parts[2], parts[3]
            short = unit.split("@")[-1].removesuffix(".service")
            states[f"{curto}:{short}"] = "ok" if active == "active" and sub == "running" else f"{active} {sub}"
    return states


def _no_da_chave(chave: str) -> str:
    _area, _, resto = chave.partition(":")
    return resto.split(":", 1)[0]


def observar() -> dict[str, str]:
    raw = docker_states()
    states = {f"{area}:{name}": raw.get(name, "ausente") for name, area in CONTAINERS}
    for name, status in raw.items():
        if name.startswith("ceph-"):
            states[f"ceph:{name}"] = status
    for key, value in ceph_units().items():
        states[f"ceph:{key}"] = value
    return states


def mudancas(anterior: dict[str, str] | None, atual: dict[str, str]) -> list[tuple[str, str, str]]:
    """Devolve (area, node, detalhe) só para o que deve ser enviado."""
    avisos = []
    nos_sem_ssh = {_no_da_chave(chave) for chave, estado in atual.items() if estado == "ssh-falhou"}
    for chave, estado in sorted(atual.items()):
        area, _, node = chave.partition(":")
        antes = None if anterior is None else anterior.get(chave)
        if antes == estado:
            continue
        if anterior is None and estado == "ok":
            continue
        detalhe = "voltou ao normal" if estado == "ok" else estado
        avisos.append((area, node, detalhe))
    if anterior:
        for chave, antes in anterior.items():
            if chave in atual or antes == "ausente":
                continue
            if _no_da_chave(chave) in nos_sem_ssh:
                continue
            area, _, node = chave.partition(":")
            avisos.append((area, node, "não apareceu nesta leitura"))
    return avisos


def enviar(area: str, node: str, detalhe: str) -> None:
    titulo = {
        "immich": "Immich",
        "bitwarden": "Bitwarden",
        "ceph": "Ceph",
        "homelab": "Homelab",
    }.get(area, area)
    payload = json.dumps({
        "titulo": titulo, "node": node[:120], "detalhe": detalhe[:900], "aprovacao": False,
    }).encode()
    request = urllib.request.Request(
        BOT + "/internal/cluster/alerta", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode())
    if not isinstance(body, dict) or body.get("ok") is not True:
        motivo = body.get("motivo", "recusado") if isinstance(body, dict) else "resposta inválida"
        raise RuntimeError(str(motivo)[:180])


def carregar() -> dict[str, str] | None:
    try:
        value = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def gravar(states: dict[str, str]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(states, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                         encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, STATE)


def main() -> int:
    atual = observar()
    anterior = carregar()
    pendentes = mudancas(anterior, atual)
    falhas = []
    enviados = set()
    for area, node, detalhe in pendentes:
        try:
            enviar(area, node, detalhe)
            enviados.add(f"{area}:{node}")
            print(f"enviado {area}:{node} {detalhe}")
        except (OSError, urllib.error.URLError, RuntimeError, ValueError) as exc:
            falhas.append(f"{area}:{node}: {type(exc).__name__}")
            print(f"falha {area}:{node}: {type(exc).__name__}")
    if anterior is None:
        gravar({chave: estado for chave, estado in atual.items()
                if estado == "ok" or chave in enviados})
    else:
        novo = dict(anterior)
        for chave, estado in atual.items():
            if estado == anterior.get(chave) or chave in enviados or estado == "ok":
                novo[chave] = estado
        gravar(novo)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
