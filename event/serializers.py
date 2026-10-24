from rest_framework import serializers

from event.models import Project



class ProjectsSerializer(serializers.ModelSerializer):

    event_name = serializers.CharField(source="event.name")
    lead_name = serializers.CharField(source="lead.first_name")

    class Meta:
        model= Project 
        fields = ['id',"name","event_name","lead_name","start_date","end_date","status","tasks"]