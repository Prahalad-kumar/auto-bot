from alembic import op
import sqlalchemy as sa


revision = "0002_seed_admin_user"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    users = sa.table(
        "users",
        sa.column("id", sa.Integer),
        sa.column("email", sa.String(255)),
        sa.column("password_hash", sa.String(255)),
        sa.column("is_active", sa.Boolean),
    )

    connection = op.get_bind()

    # Create the default user only if it doesn't already exist.
    existing_user = connection.execute(
        sa.select(users.c.id).where(
            users.c.email == "Prahaladkr1@gmail.com"
        )
    ).first()

    if existing_user is None:
        op.bulk_insert(
            users,
            [
                {
                    "email": "Prahaladkr1@gmail.com",
                    "password_hash": "$2b$12$9DRkpaE6BoLscSe/Z15/TOQkNcfLDXHVgi4mLEPsGBMntj2rHAg/S",
                    "is_active": True,
                }
            ],
        )


def downgrade():
    connection = op.get_bind()

    connection.execute(
        sa.text(
            "DELETE FROM users WHERE email = :email"
        ),
        {
            "email": "Prahaladkr1@gmail.com"
        },
    )