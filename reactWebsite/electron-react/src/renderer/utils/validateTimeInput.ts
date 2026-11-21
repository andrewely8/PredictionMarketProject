//function validateScheduledTime
// validates user form submitted time
// date: users date string input MM/DD/YYYY
// time: users time string input HH:MM
// ampm: users selected am/pm radio button option
// returns: 
//          {success: false, msg: "error message"}
// OR       {success: true, iso_time: <ISO String>}

export function validateScheduledTime(date, time, ampm) {
  const date_re = new RegExp("^([1][0-2]|0?[1-9])[/-]([1-3][0-9]|0?[1-9])[/-]([0-9][0-9][0-9][0-9]|[0-9][0-9])$");
  const time_re = new RegExp("^([0-9]?[0-9]):([0-9][0-9])$");
  const dateMatch = date_re.exec(date.trim());
  const timeMatch = time_re.exec(time.trim());
  const period = ampm?.trim().toUpperCase();
  const now = new Date();

  if (!dateMatch) {
   return ({success: false, msg: "Invalid Date: enter date as mm/dd/yyyy"});
  }
  if (!timeMatch) {
   return ({success: false, msg: "Invalid Time: enter time as hh:mm"});
  }
  
  let [raw_date_match, rawMonth, rawDay, rawYear] = dateMatch;
  let [raw_time_match, rawHour, rawMinute] = timeMatch;

  if (rawYear.length == 2) {
   rawYear = (String(now.getFullYear())).substring(0,2) + rawYear
  }
  if (rawMonth.length == 1) {
   rawMonth = 0 + rawMonth
  }
  if (rawDay.length == 1) {
   rawDay = 0 + rawDay
  }
  if (rawHour.length == 1) {
   rawHour = 0 + rawHour  
  }
  if (Number(rawHour) < 1 || Number(rawHour) > 12 || Number(rawMinute) < 0 || Number(rawMinute) > 59) {
    return { success: false, msg: "invalid time" };
  }
  if (Number(rawDay) < 1 || Number(rawDay) > 31) {
    return { success: false, msg: "invalid day" };
  }

  rawHour = (Number(rawHour) % 12) + (period === "PM" ? 12 : 0);
  const newDate = new Date(0);
  newDate.setFullYear(rawYear,rawMonth-1,rawDay);
  newDate.setHours(rawHour,rawMinute,0,0);

  if (
   newDate.getFullYear() !== Number(rawYear) ||
   newDate.getMonth() !== Number(rawMonth) - 1 ||
   newDate.getDate() !== Number(rawDay)
  ) {
   return { success: false, msg: "invalid calendar date" };
  }
  if (
    newDate.getHours() !== rawHour ||
    newDate.getMinutes() !== Number(rawMinute)
  ) {
    return { success: false, msg: "That time does not exist in your local time zone" };
  }

  if (newDate.getTime() <= Date.now()) {
   return ({success: false, msg: "specified scheduled time is not in the future"});
  } else {
   return {success: true, iso_time: newDate.toISOString()}
  }

};