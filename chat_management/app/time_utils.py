def convert_timestamps(data):
    """Convert Firestore timestamps to datetime objects"""
    timestamp_fields = ['timestamp', 'createdAt', 'lastMessageAt', 'lastActive']
    for field in timestamp_fields:
        if field in data and data[field] is not None:
            data[field] = data[field].datetime
    return data