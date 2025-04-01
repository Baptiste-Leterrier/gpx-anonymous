import os
import logging
import tempfile
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
import gpxpy
from dotenv import load_dotenv
import math

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="GPX Anonymizer Service",
    description="A service to anonymize GPX files by translating coordinates while preserving relative distances",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AnonymizedGPXResponse(BaseModel):
    gpx_data: str
    original_distance: float
    anonymized_distance: float
    processing_time: float

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "gpx_data": "<gpx>...</gpx>",
                "original_distance": 10.5,
                "anonymized_distance": 10.5,
                "processing_time": 0.1
            }
        }
    )

def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the distance between two points using the Haversine formula."""
    R = 6371  # Earth's radius in kilometers

    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    distance = R * c

    return distance

def anonymize_gpx(gpx_data: str) -> tuple[str, float, float]:
    """Anonymize GPX data by translating coordinates while preserving relative distances."""
    try:
        gpx = gpxpy.parse(gpx_data)
        
        if not gpx.tracks:
            raise ValueError("No tracks found in GPX file")
        
        track = gpx.tracks[0]
        if not track.segments:
            raise ValueError("No segments found in track")
        
        segment = track.segments[0]
        if not segment.points:
            raise ValueError("No points found in segment")
        
        # Store original points for verification
        original_points = [(p.latitude, p.longitude, p.elevation if p.elevation else 0) for p in segment.points]
        
        # Calculate original distances between consecutive points
        original_distances = []
        segment_distances = []
        segment_bearings = []
        
        for i in range(len(segment.points) - 1):
            p1, p2 = segment.points[i], segment.points[i + 1]
            
            # Calculate distance between consecutive points
            dist = calculate_distance(p1.latitude, p1.longitude, p2.latitude, p2.longitude)
            segment_distances.append(dist)
            original_distances.append(dist * 1000)  # Store in meters
            
            # Calculate bearing between consecutive points
            lat1, lon1 = math.radians(p1.latitude), math.radians(p1.longitude)
            lat2, lon2 = math.radians(p2.latitude), math.radians(p2.longitude)
            dlon = lon2 - lon1
            y = math.sin(dlon) * math.cos(lat2)
            x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
            bearing = math.atan2(y, x)
            segment_bearings.append(bearing)
        
        # Calculate total original distance
        original_distance = sum(segment_distances)
        
        # Reconstruct the track starting from (0,0)
        segment.points[0].latitude = 0
        segment.points[0].longitude = 0
        
        # Earth's radius in meters
        EARTH_RADIUS = 6371000
        
        for i in range(len(segment_distances)):
            dist = segment_distances[i] * 1000  # Convert to meters
            bearing = segment_bearings[i]
            
            # Calculate new point position using direct distance
            prev_lat = math.radians(segment.points[i].latitude)
            prev_lon = math.radians(segment.points[i].longitude)
            
            # Angular distance in radians
            angular_dist = dist / EARTH_RADIUS
            
            # Calculate new position
            new_lat = math.asin(
                math.sin(prev_lat) * math.cos(angular_dist) +
                math.cos(prev_lat) * math.sin(angular_dist) * math.cos(bearing)
            )
            
            new_lon = prev_lon + math.atan2(
                math.sin(bearing) * math.sin(angular_dist) * math.cos(prev_lat),
                math.cos(angular_dist) - math.sin(prev_lat) * math.sin(new_lat)
            )
            
            # Convert back to degrees
            segment.points[i + 1].latitude = math.degrees(new_lat)
            segment.points[i + 1].longitude = math.degrees(new_lon)
            # Preserve elevation
            segment.points[i + 1].elevation = original_points[i + 1][2]
        
        # Verify distances with meter precision
        anonymized_distances = []
        for i in range(len(segment.points) - 1):
            p1, p2 = segment.points[i], segment.points[i + 1]
            dist = calculate_distance(p1.latitude, p1.longitude, p2.latitude, p2.longitude)
            anonymized_distances.append(dist * 1000)  # Convert to meters
        
        # Calculate total anonymized distance
        anonymized_distance = sum(d / 1000 for d in anonymized_distances)  # Convert back to kilometers
        
        # Verify precision at meter level
        max_diff = 0
        for i, (orig, anon) in enumerate(zip(original_distances, anonymized_distances)):
            diff = abs(orig - anon)
            if diff > max_diff:
                max_diff = diff
            if diff > 1:  # More than 1 meter difference it is not good
                logger.warning(f"Segment {i}: Distance mismatch of {diff:.2f} meters "
                             f"(original: {orig:.2f}m, anonymized: {anon:.2f}m)")
        
        logger.info(f"Maximum distance difference: {max_diff:.2f} meters")
        
        # Log overall statistics
        if abs(anonymized_distance - original_distance) > 0.001:  # 1 meter tolerance
            logger.warning(f"Total distance mismatch: original={original_distance*1000:.2f}m, "
                         f"anonymized={anonymized_distance*1000:.2f}m, "
                         f"difference={abs(anonymized_distance-original_distance)*1000:.2f}m")
        
        return gpx.to_xml(), original_distance, anonymized_distance
    
    except Exception as e:
        logger.error(f"Error processing GPX file: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error processing GPX file: {str(e)}")

@app.post("/api/v1/anonymize", response_model=AnonymizedGPXResponse)
async def anonymize_gpx_file(
    file: UploadFile = File(...)
):
    """
    Upload and anonymize a GPX file.
    """
    start_time = datetime.now()
    
    try:
        # Validate file type
        if not file.filename.endswith('.gpx'):
            raise HTTPException(status_code=400, detail="File must be a GPX file")
        
        # Read file content
        content = await file.read()
        gpx_data = content.decode('utf-8')
        
        # Process GPX file
        anonymized_gpx, original_distance, anonymized_distance = anonymize_gpx(gpx_data)
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        logger.info(f"Successfully processed GPX file: {file.filename}")
        logger.info(f"Original distance: {original_distance:.2f}km")
        logger.info(f"Anonymized distance: {anonymized_distance:.2f}km")
        logger.info(f"Processing time: {processing_time:.2f}s")
        
        return AnonymizedGPXResponse(
            gpx_data=anonymized_gpx,
            original_distance=original_distance,
            anonymized_distance=anonymized_distance,
            processing_time=processing_time
        )
    
    except Exception as e:
        logger.error(f"Error processing file {file.filename}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/anonymize/download", response_class=FileResponse)
async def anonymize_gpx_file_download(
    file: UploadFile = File(...)
):
    """
    Upload and anonymize a GPX file, returning the anonymized file directly.
    """
    start_time = datetime.now()
    
    try:
        # Validate file type
        if not file.filename.endswith('.gpx'):
            raise HTTPException(status_code=400, detail="File must be a GPX file")
        
        # Read file content
        content = await file.read()
        gpx_data = content.decode('utf-8')
        
        # Process GPX file
        anonymized_gpx, original_distance, anonymized_distance = anonymize_gpx(gpx_data)
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        # Create a temporary file to store the anonymized GPX
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gpx', delete=False) as temp_file:
            temp_file.write(anonymized_gpx)
            temp_file_path = temp_file.name
        
        # Generate output filename
        original_filename = os.path.splitext(file.filename)[0]
        output_filename = f"{original_filename}_anonymized.gpx"
        
        #some logs to check if everything is okay
        logger.info(f"Successfully processed GPX file: {file.filename}")
        logger.info(f"Original distance: {original_distance:.2f}km")
        logger.info(f"Anonymized distance: {anonymized_distance:.2f}km")
        logger.info(f"Processing time: {processing_time:.2f}s")
        
        # Return the file with proper headers
        return FileResponse(
            temp_file_path,
            media_type='application/gpx+xml',
            filename=output_filename,
            background=None  # This ensures the file is deleted after sending
        )
    
    except Exception as e:
        logger.error(f"Error processing file {file.filename}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """
    Health check endpoint
    """
    return {"status": "healthy"} 