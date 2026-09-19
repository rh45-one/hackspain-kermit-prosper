"""Create the first account. There is no sign-up over HTTP, on purpose.

A console that serves whole call transcripts does not get a public "create an
account" form. The first person is created here, by somebody who already has
a shell on the machine — `fly ssh console` on the deployed host — and every
person after that is created the same way until there is a reason for more.

    python -m agent.accounts.bootstrap --email ana@clinica.es
    python -m agent.accounts.bootstrap --email ana@clinica.es \\
        --org clinica-sagasta --org-name "Clínica Sagasta" --role owner

The password never arrives as an argument: it is read from
`OPS_BOOTSTRAP_PASSWORD` or prompted for. A password on a command line is in
the shell history and in `ps` for everyone on the box.

A clinic's Prosper key is the same: named, never pasted.

    PROSPER_KEY_SAGASTA=... python -m agent.accounts.bootstrap \\
        --org clinica-sagasta --credential-from-env PROSPER_KEY_SAGASTA
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from agent.accounts.secrets import SecretsUnavailable
from agent.accounts.store import ROLES, Store, StoreError, store
from agent.config import settings
from agent.orgs import DEFAULT_ORG_ID, InvalidOrgId, normalize_org_id


def _password(prompt: str = "Contraseña: ") -> str:
    """From the environment, or typed. Never from a command line argument."""
    from_env = os.environ.get("OPS_BOOTSTRAP_PASSWORD")
    if from_env:
        return from_env
    first = getpass.getpass(prompt)
    if first != getpass.getpass("Repítela: "):
        raise SystemExit("las contraseñas no coinciden")
    if len(first) < 12:
        raise SystemExit("usa al menos 12 caracteres")
    return first


def _ensure_org(platform: Store, org_id: str, name: str | None) -> str:
    if platform.get_organization(org_id) is None:
        platform.create_organization(org_id, name or org_id)
        print(f"organización creada: {org_id}")
    elif name:
        print(f"organización ya existente: {org_id} (el nombre no se cambia aquí)")
    return org_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Alta de organizaciones y personas")
    parser.add_argument("--email", help="correo de la persona a crear o actualizar")
    parser.add_argument("--name", default="", help="nombre visible")
    parser.add_argument("--org", default=DEFAULT_ORG_ID, help="id de la organización")
    parser.add_argument("--org-name", default=None, help="nombre de la organización si hay que crearla")
    parser.add_argument("--role", default="owner", choices=ROLES)
    parser.add_argument(
        "--set-password",
        action="store_true",
        help="cambiar la contraseña de una cuenta que ya existe (cierra sus sesiones)",
    )
    parser.add_argument(
        "--credential-from-env",
        metavar="VAR",
        help="guardar la clave de Prosper de la organización leyéndola de esa variable",
    )
    args = parser.parse_args(argv)

    config = settings()
    platform = store(config)
    platform.migrate()

    try:
        org_id = normalize_org_id(args.org)
    except InvalidOrgId as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    _ensure_org(platform, org_id, args.org_name)

    if args.credential_from_env:
        api_key = os.environ.get(args.credential_from_env, "")
        if not api_key:
            print(f"error: {args.credential_from_env} está vacía", file=sys.stderr)
            return 2
        try:
            org = platform.set_organization_credential(org_id, api_key, config.ops_secret_key)
        except SecretsUnavailable as exc:
            # Never write it in the clear as a fallback.
            print(f"error: {exc}", file=sys.stderr)
            return 3
        # The fingerprint, never the key.
        print(f"credencial guardada para {org_id}: {org.credential_fingerprint}")

    if not args.email:
        return 0

    existing = platform.get_user_by_email(args.email)
    try:
        if existing is None:
            user = platform.create_user(args.email, _password(), args.name)
            print(f"persona creada: {user.email}")
        else:
            user = existing
            if args.set_password:
                platform.set_password(user.id, _password("Contraseña nueva: "))
                print(f"contraseña cambiada: {user.email} (sus sesiones se han cerrado)")
        platform.add_membership(user.id, org_id, args.role)
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"pertenencia: {user.email} -> {org_id} como {args.role}")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
