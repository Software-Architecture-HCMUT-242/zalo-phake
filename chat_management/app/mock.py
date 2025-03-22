
from faker import Faker
import random
from .messages.schemas import Message
from .chats.schemas import Chat

fake = Faker()

def get_fake_user(user_id):
    user = {
        'user_id': user_id,
        'name': fake.name(),
        'profilePicture': fake.image_url(),
        'status': fake.sentence(nb_words=6),
        'lastSeen': fake.date_time_this_year().isoformat()
    }
    return user

def random_chat() -> Chat:
    chat = Chat(
        chatId=fake.uuid4(),
        lastMessageTime=fake.date_time_this_year().isoformat(),
        lastMessagePreview=fake.sentence(nb_words=6),
        participants=[random_phone_number() for _ in range(random.randint(0, 5))]
    )
    return chat
    
def random_message() -> Message:
    from .messages.schemas import Message
    message = Message(
        messageId=fake.uuid4(),
        senderId=random_phone_number(),
        content=fake.sentence(nb_words=6),
        messageType=random.choice(['text', 'image', 'video', 'audio']),
        timestamp=fake.date_time_this_year().isoformat(),
        readBy=[random_phone_number() for _ in range(random.randint(0, 5))]   
    )
    return message

phone_fake = Faker('vi_VN')
def random_phone_number() -> str:
    return phone_fake.phone_number().replace(' ', '').replace('-', '').replace('+84', '0').replace('(', '').replace(')', '')