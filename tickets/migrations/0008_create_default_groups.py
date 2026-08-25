from django.db import migrations

GROUP_NAMES = ['Requesters', 'ICT Agents', 'Administrators']


def create_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    for name in GROUP_NAMES:
        Group.objects.get_or_create(name=name)


def remove_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name__in=GROUP_NAMES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0007_category_default_priority_ticket_escalation_level_and_more'),
        ('auth', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_groups, reverse_code=remove_groups),
    ]
