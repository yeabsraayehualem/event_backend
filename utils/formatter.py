import json
class Formatter:

    @staticmethod
    def success(data={},status_code=200,message="Success"):
        print(str(data))
        try:
            return {
                "data":data,
                "status_code":status_code,
                "message":message
            }
        except Exception as e:
            return Formatter.error_response(data={},message=str(e))
          
    @staticmethod
    def error_response(data={},message="",status_code=500):
             return {
                "data":data,
                "status_code":status_code,
                "message": message
                }


