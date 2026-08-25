import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group
from django.utils import timezone

from tickets.models import Category, Priority, Department, Location, Profile, Ticket, Notification


TITLE_POOL = {
    'network': [
        "No internet connection in office",
        "WiFi keeps disconnecting",
        "VPN not connecting",
        "Email not syncing",
        "Very slow network speed",
    ],
    'hardware': [
        "Computer won't power on",
        "Monitor showing no display",
        "Keyboard not responding",
        "Laptop battery not charging",
        "UPS not backing up power",
    ],
    'software': [
        "Application keeps crashing",
        "Need software installed",
        "Windows update stuck",
        "MS Word not opening",
        "Antivirus showing alerts",
    ],
    'account': [
        "Forgot my password",
        "Account locked out",
        "Need new user account",
        "Need access to shared drive",
        "Email account not configured",
    ],
    'printer': [
        "Printer not responding",
        "Paper jam in printer",
        "Printer out of toner",
        "Poor print quality",
        "Network printer not found",
    ],
}
DEFAULT_TITLES = [
    "Need IT assistance",
    "General technical issue",
    "Request for support",
    "Equipment relocation needed",
    "Data backup request",
]

DEMO_REQUESTERS = [
    ("mary_wanjiku", "Mary", "Wanjiku", "0712345671"),
    ("peter_ochieng", "Peter", "Ochieng", "0712345672"),
    ("grace_mwikali", "Grace", "Mwikali", "0712345673"),
]

DEMO_AGENTS = [
    ("agent_mwangi", "James", "Mwangi", "0722334455"),
    ("agent_amina", "Amina", "Hassan", "0733445566"),
]

# Category name → Priority name mapping (rule-based auto-priority)
CATEGORY_PRIORITY_MAP = {
    'Network Issues': 'High',
    'Network Issue': 'High',
    'Hardware Fault': 'High',
    'Software Issue': 'Medium',
    'Account/Access Issue': 'Medium',
    'Printer Issue': 'Low',
    'Other': 'Low',
}


def pick_title(category_name):
    key = category_name.lower()
    for k, titles in TITLE_POOL.items():
        if k in key:
            return random.choice(titles)
    return random.choice(DEFAULT_TITLES)


class Command(BaseCommand):
    help = "Seeds the database with demo data showcasing all automation features."

    def handle(self, *args, **options):
        # ── Reference data: categories, priorities, departments, locations ──
        priority_defs = [
            ('Critical', 2), ('High', 4), ('Medium', 24), ('Low', 72),
        ]
        for name, hours in priority_defs:
            Priority.objects.get_or_create(name=name, defaults={'escalation_hours': hours})

        for name in [
            'Network Issues', 'Hardware Fault', 'Software Issue',
            'Account/Access Issue', 'Printer Issue', 'Other',
        ]:
            Category.objects.get_or_create(name=name)

        for name in [
            'Executive', 'Deputy Governor Building', 'Land & Planning',
            'Betting and Control', 'County Board of Mombasa',
        ]:
            Location.objects.get_or_create(name=name)

        for name in ['ICT Department', 'Finance', 'Human Resource', 'Administration']:
            Department.objects.get_or_create(name=name)

        categories = list(Category.objects.all())
        priorities = list(Priority.objects.all())
        departments = list(Department.objects.all())
        locations = list(Location.objects.all())

        # ── Set up category → priority mappings (auto-priority rules) ──
        priority_map = {p.name: p for p in priorities}
        mapped_count = 0
        for cat in categories:
            target_priority_name = CATEGORY_PRIORITY_MAP.get(cat.name)
            if target_priority_name and target_priority_name in priority_map:
                cat.default_priority = priority_map[target_priority_name]
                cat.save()
                mapped_count += 1

        self.stdout.write(f"  Mapped {mapped_count} categories to default priorities.")

        # ── Create demo users ──
        requesters_group, _ = Group.objects.get_or_create(name='Requesters')
        agents_group, _ = Group.objects.get_or_create(name='ICT Agents')
        Group.objects.get_or_create(name='Administrators')

        requesters = []
        for username, first, last, phone in DEMO_REQUESTERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={'first_name': first, 'last_name': last, 'email': f'{username}@mombasa.go.ke'}
            )
            if created:
                user.set_password('demo12345')
                user.save()
            user.groups.add(requesters_group)
            requesters.append((user, phone))

        agents = []
        for username, first, last, phone in DEMO_AGENTS:
            agent, created = User.objects.get_or_create(
                username=username,
                defaults={'first_name': first, 'last_name': last, 'email': f'{username}@mombasa.go.ke'}
            )
            if created:
                agent.set_password('demo12345')
                agent.save()
            agent.groups.add(agents_group)
            Profile.objects.update_or_create(
                user=agent,
                defaults={'phone_number': phone}
            )
            agents.append(agent)

        # ── Create demo tickets ──
        statuses = ['open', 'in_progress', 'in_progress', 'resolved', 'resolved', 'closed']
        created_count = 0

        for i in range(25):
            category = random.choice(categories)
            department = random.choice(departments) if departments else None
            location = random.choice(locations) if locations else None
            requester, requester_phone = random.choice(requesters)
            status = random.choice(statuses)

            days_ago = random.randint(0, 25)
            created_time = timezone.now() - timedelta(days=days_ago, hours=random.randint(0, 23))

            # Create ticket — signal auto-assigns agent + auto-sets priority from category
            ticket = Ticket.objects.create(
                title=pick_title(category.name),
                description="Reported via the help desk system.",
                category=category,
                department=department,
                location=location,
                status='open',
                contact_phone=requester_phone,
                requester=requester,
            )

            # Override created_at and status for demo variety
            update_fields = {'created_at': created_time, 'status': status}

            if status in ('resolved', 'closed'):
                update_fields['assigned_agent_id'] = random.choice(agents).id
                update_fields['resolved_at'] = created_time + timedelta(hours=random.randint(1, 48))
            elif status == 'in_progress':
                update_fields['assigned_agent_id'] = random.choice(agents).id

            if status in ('open', 'in_progress') and random.random() < 0.15:
                update_fields['escalation_level'] = 1

            Ticket.objects.filter(pk=ticket.pk).update(**update_fields)
            created_count += 1

        # Clear auto-generated notifications from seeding — unread badges from
        # seed data would misleadingly suggest a live demo already happened.
        # AuditLog entries are kept: they're the historical record the dashboard
        # and ticket detail pages display, and seeded tickets should show one.
        Notification.objects.filter(
            ticket__description="Reported via the help desk system."
        ).delete()

        self.stdout.write(self.style.SUCCESS(
            f"Created {created_count} demo tickets, {len(requesters)} requesters, "
            f"{len(agents)} agents. Category->Priority mappings set. "
            f"Seed notifications cleared."
        ))
