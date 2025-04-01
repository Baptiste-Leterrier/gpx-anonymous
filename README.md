# gpx-anonymous

A web service that anonymizes GPX files by translating their coordinates to 0,0 while maintaining relative distances and durations.

## Features

- Coordinate translation to (0,0) while preserving relative distances
- Time and duration preservation
- Comprehensive logging

## Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with the following variables:
```
LOG_LEVEL=INFO 
```

4. Run the service:
```bash
uvicorn main:app --reload
```

### Endpoints

- POST `/api/v1/anonymize`: Upload and anonymize a GPX file
  - Accepts multipart/form-data with a file field named "file"
  - Returns JSON with the anonymized GPX data

- POST `/api/v1/anonymize/download`: Upload and anonymize a GPX file
  - Accepts multipart/form-data with a file field named "file"
  - Returns the anonymized GPX file directly for download
  - The output filename will be the original filename with "_anonymized" suffix


### Query example


Upload a GPX file to be anonymized and return a JSON with:
- The anonymized GPX data
- original_distance
- anonymized_distance
- processing_time

```bash
curl --request POST \
  --url http://127.0.0.1:8000/api/v1/anonymize \
  --header 'content-type: multipart/form-data' \
  --form file=@file
```

Upload a GPX file and return the XML of the anonymized GPX ready to be downloaded into a file.

```bash
curl --request POST \
  --url http://127.0.0.1:8000/api/v1/anonymize/download \
  --header 'content-type: multipart/form-data' \
  --form file=@file
```
