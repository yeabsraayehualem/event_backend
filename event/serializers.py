from rest_framework import serializers

from event.models import Project



class ProjectsSerializer(serializers.ModelSerializer):

    class Meta:
        model= Project 
        fields = ['id',"name","event","lead","start_date","end_date","status"]