"""Dev convenience: create a local CDM identity, grant roles, print a JWT.

    python manage.py bootstrap_dev --email you@healthtree.org --roles admin,prompt_author

Prints an access token you can paste as `Authorization: Bearer <token>` to
exercise the API locally. Dev-only; real users sign in via partner auth.
"""
from django.core.management.base import BaseCommand
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Identity, Role, RoleAssignment


class Command(BaseCommand):
    help = "Create a local dev identity with roles and print a JWT."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--password", default="devpassword123")
        parser.add_argument("--roles", default="admin", help="comma-separated: reviewer,prompt_author,admin")

    def handle(self, *args, **opts):
        email = opts["email"]
        identity = Identity.objects.filter(issuer="urn:local", email=email).first()
        created = identity is None
        if created:
            # Use the manager so a UUID `sub` is assigned (the model requires a
            # unique sub; creating via get_or_create would leave it empty).
            identity = Identity.objects.create_superuser(
                email=email, password=opts["password"], name=email
            )

        valid = {r.value for r in Role}
        for role in (r.strip() for r in opts["roles"].split(",") if r.strip()):
            if role not in valid:
                self.stderr.write(f"skipping unknown role: {role}")
                continue
            RoleAssignment.objects.get_or_create(identity=identity, role=role)

        token = RefreshToken.for_user(identity).access_token
        self.stdout.write(self.style.SUCCESS(f"identity: {identity} ({'created' if created else 'existing'})"))
        self.stdout.write(f"roles: {identity.roles}")
        self.stdout.write(f"access token:\n{token}")
