const xlsx = require("xlsx");
const fs = require("fs");
const { faker } = require("@faker-js/faker");

function generateRow(index) {
  return {
    Transaction_ID: faker.string.uuid(),                         // 🆕 Unique identifier
    Username: faker.person.fullName(),
    Email: "eventsnssnt@gmail.com",
    Phone: faker.phone.number("###-###-####"),
    Address: index % 3 === 0 ? "" : faker.location.streetAddress(),
    "Membership Paid": index % 4 === 0 ? "" : faker.datatype.boolean(),
    "Early Bird Applied": index % 5 === 0 ? "" : faker.datatype.boolean(),
    "Payment Date": faker.date.recent({ days: 30 }).toISOString(),
    Amount: faker.finance.amount({ min: 50, max: 250, dec: 2 }),
    "Paid For": faker.helpers.arrayElement([
      "1 adult",
      "2 adults, 1 child",
      "Family of 4",
      "1 student",
      "3 kids",
    ]),
    Remarks: index % 6 === 0 ? "" : faker.lorem.sentence(),
    QR_Generated: false,                                         // 🆕 default false
    QR_Sent: false                                               // 🆕 default false
  };
}

const data = [];
for (let i = 1; i <= 20; i++) {
  data.push(generateRow(i));
}

const ws = xlsx.utils.json_to_sheet(data);
const wb = xlsx.utils.book_new();
xlsx.utils.book_append_sheet(wb, ws, "EventPayments");

xlsx.writeFile(wb, "sample_event_payments.xlsx");

console.log("✅ Excel file created: sample_event_payments.xlsx");
