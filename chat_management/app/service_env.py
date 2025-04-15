import os
class Environment:
    @staticmethod
    def get_env():
        env = os.getenv('ENVIRONMENT', 'DEV')
        if env not in ['DEV', 'PROD']:
            raise ValueError("ENVIRONMENT must be either 'DEV' or 'PROD'")

    @staticmethod
    def is_dev_environment():
        return Environment.get_env() == 'DEV'

    @staticmethod
    def is_prod_environment():
        return Environment.get_env() == 'PROD'

