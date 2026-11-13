# The Django example project is run by tests/test_model_django.py in its own
# processes, with Django installed; the main test run doesn't collect it.
collect_ignore = ["django_project"]
