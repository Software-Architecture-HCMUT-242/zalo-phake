import os
class Environment:
    @staticmethod
    def get_env():
        return os.getenv('ENVIRONMENT', 'DEV')

    @staticmethod
    def is_dev_environment():
        return Environment.get_env() == 'DEV'

    @staticmethod
    def is_prod_environment():
        return Environment.get_env() == 'PROD'

